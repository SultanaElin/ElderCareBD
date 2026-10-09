import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../models/prescription_extraction.dart';
import '../services/api_service.dart';
import '../services/prescription_image_picker.dart';
import '../services/session_service.dart';
import '../utils/app_colors.dart';
import '../utils/app_strings.dart';
import '../widgets/app_card.dart';
import '../widgets/primary_button.dart';
import '../widgets/responsive_content.dart';

class PrescriptionInputScreen extends StatefulWidget {
  final PrescriptionImagePicker? imagePicker;

  const PrescriptionInputScreen({super.key, this.imagePicker});

  @override
  State<PrescriptionInputScreen> createState() =>
      _PrescriptionInputScreenState();
}

class _PrescriptionInputScreenState extends State<PrescriptionInputScreen> {
  final doctorNameController = TextEditingController();
  final prescriptionNoteController = TextEditingController();
  final medicineNameController = TextEditingController();
  final strengthController = TextEditingController();
  final dosageController = TextEditingController();
  final frequencyController = TextEditingController();
  final durationController = TextEditingController();
  final medicineInstructionsController = TextEditingController();

  late final PrescriptionImagePicker _imagePicker;
  final List<_ReviewMedicine> _medicines = [];
  int _nextMedicineKey = 1;

  Uint8List? selectedImageBytes;
  String? selectedImageName;
  int? _createdPrescriptionId;
  bool _uploadedHasImage = false;
  bool _isPickingImage = false;
  bool _isUploading = false;
  bool _isExtracting = false;
  bool _isConfirming = false;
  bool _showOcrText = false;

  PrescriptionOcrStatus _ocrStatus = PrescriptionOcrStatus.unknown;
  String? _ocrText;
  String? _ocrEngine;
  List<String> _ocrLanguages = const [];
  List<String> _extractionWarnings = const [];
  String? _extractionError;

  bool get _hasCreatedPrescription => _createdPrescriptionId != null;
  bool get _isBusy =>
      _isPickingImage || _isUploading || _isExtracting || _isConfirming;

  @override
  void initState() {
    super.initState();
    _imagePicker = widget.imagePicker ?? DevicePrescriptionImagePicker();
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
      unawaited(_recoverLostImage());
    }
  }

  @override
  void dispose() {
    doctorNameController.dispose();
    prescriptionNoteController.dispose();
    medicineNameController.dispose();
    strengthController.dispose();
    dosageController.dispose();
    frequencyController.dispose();
    durationController.dispose();
    medicineInstructionsController.dispose();
    super.dispose();
  }

  Future<void> _recoverLostImage() async {
    try {
      final image = await _imagePicker.recoverLostImage();
      if (!mounted || image == null || _hasCreatedPrescription) return;
      _setSelectedImage(image);
      _showMessage('Recovered the prescription photo selected earlier.');
    } on Exception {
      if (mounted) {
        _showMessage(
          'A previous prescription photo could not be recovered. Please select it again.',
        );
      }
    }
  }

  Future<void> _pickPrescriptionImage(PrescriptionImageSource source) async {
    if (_isBusy || _hasCreatedPrescription) return;
    setState(() => _isPickingImage = true);
    try {
      final image = await _imagePicker.pick(source);
      if (!mounted || image == null) return;
      _setSelectedImage(image);
    } on Exception {
      if (mounted) {
        _showMessage(
          source == PrescriptionImageSource.camera
              ? 'Could not take a prescription photo. Please try again or use the gallery.'
              : 'Could not choose that prescription image. Please try again.',
        );
      }
    } finally {
      if (mounted) setState(() => _isPickingImage = false);
    }
  }

  void _setSelectedImage(PickedPrescriptionImage image) {
    setState(() {
      selectedImageBytes = image.bytes;
      selectedImageName = image.name;
    });
  }

  void _removeSelectedImage() {
    if (_isBusy || _hasCreatedPrescription) return;
    setState(() {
      selectedImageBytes = null;
      selectedImageName = null;
    });
  }

  void _addMedicine() {
    final name = medicineNameController.text.trim();
    if (name.isEmpty) {
      _showMessage('Please enter a medicine name.');
      return;
    }

    setState(() {
      _medicines.add(
        _ReviewMedicine(
          key: _nextMedicineKey++,
          candidate: PrescriptionMedicineCandidate(
            name: name,
            strength: strengthController.text.trim(),
            dosage: dosageController.text.trim(),
            frequency: frequencyController.text.trim(),
            duration: durationController.text.trim(),
            instructions: medicineInstructionsController.text.trim(),
          ),
          fromExtraction: false,
        ),
      );
      _clearMedicineForm();
    });
  }

  void _clearMedicineForm() {
    medicineNameController.clear();
    strengthController.clear();
    dosageController.clear();
    frequencyController.clear();
    durationController.clear();
    medicineInstructionsController.clear();
  }

  void _updateMedicine(int key, PrescriptionMedicineCandidate candidate) {
    final index = _medicines.indexWhere((entry) => entry.key == key);
    if (index != -1) _medicines[index].candidate = candidate;
  }

  void _deleteMedicine(int key) {
    setState(() {
      _medicines.removeWhere((entry) => entry.key == key);
    });
  }

  Future<void> _uploadPrescription() async {
    if (_isBusy || _hasCreatedPrescription) return;
    if (selectedImageBytes == null && _medicines.isEmpty) {
      _showMessage('Add a medicine or select a prescription image first.');
      return;
    }

    setState(() => _isUploading = true);
    try {
      final patientId = await SessionService.getSelectedPatientId();
      if (patientId == null) {
        if (mounted) {
          _showMessage('Please save or select a patient profile first.');
        }
        return;
      }

      final result = await ApiService.createPrescription(
        patientId: patientId,
        doctorName: doctorNameController.text.trim(),
        note: prescriptionNoteController.text.trim(),
        imageBytes: selectedImageBytes,
        imageName: selectedImageName,
      );
      if (!mounted) return;

      final statusCode = result['statusCode'];
      if (statusCode is! int || statusCode < 200 || statusCode >= 300) {
        _showMessage(
          ApiService.errorMessage(
            result,
            fallback: 'Could not upload the prescription.',
          ),
        );
        return;
      }

      final body = result['body'];
      final rawId = body is Map ? body['prescription_id'] : null;
      final prescriptionId = rawId is int
          ? rawId
          : int.tryParse(rawId?.toString() ?? '');
      if (prescriptionId == null) {
        _showMessage(
          'The prescription was saved, but the server did not return its ID.',
        );
        return;
      }

      setState(() {
        _createdPrescriptionId = prescriptionId;
        _uploadedHasImage = selectedImageBytes != null;
        _ocrStatus = _uploadedHasImage
            ? PrescriptionOcrStatus.uploaded
            : PrescriptionOcrStatus.unknown;
      });
      _showMessage(
        _uploadedHasImage
            ? 'Prescription uploaded. Extract medicines, then review every field before confirming.'
            : 'Prescription saved. Review the medicines before confirming.',
      );
    } on ApiException catch (error) {
      if (mounted) _showMessage(error.message);
    } on Exception {
      if (mounted) {
        _showMessage('Could not upload the prescription. Please try again.');
      }
    } finally {
      if (mounted) setState(() => _isUploading = false);
    }
  }

  Future<void> _extractMedicines() async {
    final prescriptionId = _createdPrescriptionId;
    if (_isBusy || prescriptionId == null || !_uploadedHasImage) return;

    setState(() {
      _isExtracting = true;
      _ocrStatus = PrescriptionOcrStatus.processing;
      _extractionError = null;
    });
    try {
      final result = await ApiService.extractPrescription(
        prescriptionId: prescriptionId,
      );
      if (!mounted) return;

      final manualEntries = _medicines
          .where((entry) => !entry.fromExtraction)
          .toList(growable: false);
      final extractedEntries = result.candidates
          .map(
            (candidate) => _ReviewMedicine(
              key: _nextMedicineKey++,
              candidate: candidate,
              fromExtraction: true,
            ),
          )
          .toList(growable: false);

      setState(() {
        _ocrStatus = result.status;
        _ocrText = result.ocrText;
        _ocrEngine = result.ocrEngine;
        _ocrLanguages = result.ocrLanguages;
        _extractionWarnings = result.warnings;
        _medicines
          ..clear()
          ..addAll(manualEntries)
          ..addAll(extractedEntries);
        _extractionError = result.status == PrescriptionOcrStatus.failed
            ? _firstWarningOr(
                result.warnings,
                'Medicine extraction failed. You can still add medicines manually.',
              )
            : result.candidates.isEmpty
            ? 'No medicine candidates were found. Add the medicines manually before confirming.'
            : null;
      });

      if (result.status == PrescriptionOcrStatus.ready &&
          result.candidates.isNotEmpty) {
        _showMessage(
          '${result.candidates.length} candidate medicine(s) found. Please review and correct them.',
        );
      }
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _ocrStatus = PrescriptionOcrStatus.failed;
        _extractionError = '${error.message} You can add medicines manually.';
      });
      _showMessage(error.message);
    } on Exception {
      if (!mounted) return;
      setState(() {
        _ocrStatus = PrescriptionOcrStatus.failed;
        _extractionError =
            'Medicine extraction failed. You can add medicines manually.';
      });
      _showMessage('Could not extract medicines. Please enter them manually.');
    } finally {
      if (mounted) setState(() => _isExtracting = false);
    }
  }

  Future<void> _confirmReviewedMedicines() async {
    final prescriptionId = _createdPrescriptionId;
    if (_isBusy || prescriptionId == null) return;
    if (_medicines.isEmpty) {
      _showMessage('Add at least one reviewed medicine before confirming.');
      return;
    }

    final invalidIndex = _medicines.indexWhere(
      (entry) => entry.candidate.name.trim().isEmpty,
    );
    if (invalidIndex != -1) {
      _showMessage(
        'Medicine ${invalidIndex + 1} needs a name before confirmation.',
      );
      return;
    }

    setState(() => _isConfirming = true);
    try {
      final result = await ApiService.confirmPrescription(
        prescriptionId: prescriptionId,
        medicines: _medicines
            .map((entry) => entry.candidate.toConfirmationJson())
            .toList(growable: false),
      );
      if (!mounted) return;

      final statusCode = result['statusCode'];
      if (statusCode is! int || statusCode < 200 || statusCode >= 300) {
        _showMessage(
          ApiService.errorMessage(
            result,
            fallback:
                'The prescription was saved, but its medicines could not be confirmed.',
          ),
        );
        return;
      }

      _showMessage(
        'Prescription and ${_medicines.length} reviewed medicine(s) saved successfully.',
      );
      Navigator.pop(context, true);
    } on ApiException catch (error) {
      if (mounted) _showMessage(error.message);
    } on Exception {
      if (mounted) {
        _showMessage('Could not confirm the medicines. Please try again.');
      }
    } finally {
      if (mounted) setState(() => _isConfirming = false);
    }
  }

  void _showMessage(String message) {
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  String _firstWarningOr(List<String> warnings, String fallback) {
    return warnings.isEmpty ? fallback : warnings.first;
  }

  @override
  Widget build(BuildContext context) {
    final strings = AppStrings.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(strings.prescription)),
      body: ResponsiveContent(
        maxWidth: 820,
        child: SingleChildScrollView(
          keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const _IntroCard(),
              const SizedBox(height: 20),
              _sectionTitle('Prescription image'),
              const SizedBox(height: 12),
              _buildImageCard(),
              const SizedBox(height: 22),
              _sectionTitle('Prescription details'),
              const SizedBox(height: 12),
              TextField(
                controller: doctorNameController,
                enabled: !_hasCreatedPrescription,
                decoration: const InputDecoration(
                  labelText: 'Doctor name / hospital',
                  prefixIcon: Icon(Icons.local_hospital_rounded),
                ),
              ),
              const SizedBox(height: 14),
              TextField(
                controller: prescriptionNoteController,
                enabled: !_hasCreatedPrescription,
                maxLines: 3,
                decoration: const InputDecoration(
                  labelText: 'Prescription note',
                  hintText: 'Example: Follow-up after 2 weeks',
                  alignLabelWithHint: true,
                ),
              ),
              const SizedBox(height: 16),
              if (!_hasCreatedPrescription)
                _ProgressAction(
                  busy: _isUploading,
                  label: selectedImageBytes == null
                      ? 'Save Prescription Details'
                      : 'Upload Prescription',
                  icon: Icons.cloud_upload_rounded,
                  onPressed: _uploadPrescription,
                )
              else
                _UploadedNotice(prescriptionId: _createdPrescriptionId!),
              if (_hasCreatedPrescription && _uploadedHasImage) ...[
                const SizedBox(height: 16),
                _ProgressAction(
                  busy: _isExtracting,
                  label: _ocrStatus == PrescriptionOcrStatus.ready
                      ? 'Extract Medicines Again'
                      : 'Extract Medicines',
                  icon: Icons.document_scanner_rounded,
                  onPressed: _extractMedicines,
                ),
              ],
              if (_hasCreatedPrescription) ...[
                const SizedBox(height: 22),
                _buildExtractionReview(),
              ],
              const SizedBox(height: 22),
              _sectionTitle(
                _hasCreatedPrescription
                    ? 'Add a missed medicine'
                    : 'Add medicine manually',
              ),
              const SizedBox(height: 8),
              Text(
                'Only medicine name is required. Leave details blank when they are unknown.',
                style: TextStyle(color: AppColors.textSoft, height: 1.4),
              ),
              const SizedBox(height: 12),
              _buildManualMedicineForm(),
              if (_medicines.isNotEmpty) ...[
                const SizedBox(height: 22),
                _sectionTitle('Medicines to review'),
                const SizedBox(height: 8),
                Text(
                  'OCR suggestions are not final. Check and edit every medicine before confirming.',
                  style: TextStyle(color: AppColors.textSoft, height: 1.4),
                ),
                const SizedBox(height: 12),
                ..._medicines.map(
                  (entry) => _MedicineReviewCard(
                    key: ValueKey('review-medicine-${entry.key}'),
                    index: _medicines.indexOf(entry),
                    medicine: entry,
                    onChanged: (candidate) =>
                        _updateMedicine(entry.key, candidate),
                    onDelete: () => _deleteMedicine(entry.key),
                  ),
                ),
              ],
              if (_hasCreatedPrescription) ...[
                const SizedBox(height: 24),
                _ProgressAction(
                  busy: _isConfirming,
                  label: '${strings.confirm} Reviewed Medicines',
                  icon: Icons.verified_rounded,
                  onPressed: _confirmReviewedMedicines,
                ),
              ],
              const SizedBox(height: 24),
            ],
          ),
        ),
      ),
    );
  }

  Widget _sectionTitle(String title) {
    return Text(
      title,
      style: TextStyle(
        fontSize: 20,
        fontWeight: FontWeight.w900,
        color: AppColors.primary,
      ),
    );
  }

  Widget _buildImageCard() {
    return AppCard(
      child: Column(
        children: [
          if (selectedImageBytes == null)
            Container(
              height: 180,
              width: double.infinity,
              decoration: BoxDecoration(
                color: AppColors.mint,
                borderRadius: BorderRadius.circular(20),
                border: Border.all(color: AppColors.border),
              ),
              child: const Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(
                    Icons.image_outlined,
                    size: 58,
                    color: AppColors.primary,
                  ),
                  SizedBox(height: 8),
                  Text('No prescription image selected'),
                ],
              ),
            )
          else
            ClipRRect(
              borderRadius: BorderRadius.circular(20),
              child: Image.memory(
                selectedImageBytes!,
                height: 230,
                width: double.infinity,
                fit: BoxFit.contain,
                errorBuilder: (context, error, stackTrace) => const SizedBox(
                  height: 160,
                  child: Center(child: Text('Image preview unavailable')),
                ),
              ),
            ),
          const SizedBox(height: 14),
          if (!_hasCreatedPrescription) ...[
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: _isBusy
                    ? null
                    : () => _pickPrescriptionImage(
                        PrescriptionImageSource.camera,
                      ),
                icon: const Icon(Icons.photo_camera_rounded),
                label: const Text('Take photo'),
              ),
            ),
            const SizedBox(height: 10),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: _isBusy
                    ? null
                    : () => _pickPrescriptionImage(
                        PrescriptionImageSource.gallery,
                      ),
                icon: const Icon(Icons.photo_library_rounded),
                label: const Text('Choose from gallery'),
              ),
            ),
            if (selectedImageBytes != null)
              TextButton.icon(
                onPressed: _isBusy ? null : _removeSelectedImage,
                icon: const Icon(Icons.delete_outline_rounded),
                label: const Text('Remove selected image'),
              ),
          ],
          if (selectedImageName != null) ...[
            const SizedBox(height: 4),
            Text(
              'Selected: $selectedImageName',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: AppColors.textSoft),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildExtractionReview() {
    if (!_uploadedHasImage) {
      return const _ReviewNotice(
        icon: Icons.edit_note_rounded,
        message:
            'This prescription has no image. Add the medicines manually, review them, then confirm.',
      );
    }

    final statusText = switch (_ocrStatus) {
      PrescriptionOcrStatus.uploaded => 'Uploaded — extraction not started',
      PrescriptionOcrStatus.processing => 'Extracting medicine candidates…',
      PrescriptionOcrStatus.ready => 'Candidates ready for caregiver review',
      PrescriptionOcrStatus.failed =>
        'Extraction failed — manual entry available',
      PrescriptionOcrStatus.confirmed => 'Confirmed',
      PrescriptionOcrStatus.unknown => 'Status unavailable',
    };

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'OCR review',
            style: TextStyle(
              fontSize: 17,
              fontWeight: FontWeight.w800,
              color: AppColors.textDark,
            ),
          ),
          const SizedBox(height: 8),
          Text(statusText, key: const Key('ocr-status-text')),
          if (_ocrEngine != null || _ocrLanguages.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              [
                if (_ocrEngine != null) 'Engine: $_ocrEngine',
                if (_ocrLanguages.isNotEmpty)
                  'Languages: ${_ocrLanguages.join(', ')}',
              ].join(' · '),
              style: TextStyle(color: AppColors.textSoft, fontSize: 12),
            ),
          ],
          if (_extractionError != null) ...[
            const SizedBox(height: 12),
            _WarningBox(message: _extractionError!),
          ],
          if (_extractionWarnings.isNotEmpty) ...[
            const SizedBox(height: 10),
            ..._extractionWarnings.map(
              (warning) => Padding(
                padding: const EdgeInsets.only(bottom: 5),
                child: Text('• $warning'),
              ),
            ),
          ],
          if (_ocrText != null) ...[
            const SizedBox(height: 12),
            OutlinedButton.icon(
              key: const Key('toggle-ocr-text'),
              onPressed: () => setState(() => _showOcrText = !_showOcrText),
              icon: Icon(
                _showOcrText
                    ? Icons.visibility_off_rounded
                    : Icons.visibility_rounded,
              ),
              label: Text(
                _showOcrText
                    ? 'Hide raw extracted text'
                    : 'Review raw extracted text',
              ),
            ),
            if (_showOcrText)
              Container(
                key: const Key('raw-ocr-text'),
                width: double.infinity,
                margin: const EdgeInsets.only(top: 10),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: AppColors.mint,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AppColors.border),
                ),
                child: SelectableText(_ocrText!),
              ),
          ],
        ],
      ),
    );
  }

  Widget _buildManualMedicineForm() {
    return Column(
      children: [
        TextField(
          key: const Key('manual-medicine-name'),
          controller: medicineNameController,
          decoration: const InputDecoration(
            labelText: 'Medicine name',
            prefixIcon: Icon(Icons.medication_rounded),
          ),
        ),
        const SizedBox(height: 14),
        TextField(
          controller: strengthController,
          decoration: const InputDecoration(
            labelText: 'Strength (optional)',
            hintText: '500 mg',
          ),
        ),
        const SizedBox(height: 14),
        TextField(
          controller: dosageController,
          decoration: const InputDecoration(
            labelText: 'Dose amount (optional)',
            hintText: '1 tablet',
          ),
        ),
        const SizedBox(height: 14),
        TextField(
          controller: frequencyController,
          decoration: const InputDecoration(
            labelText: 'Frequency (optional)',
            hintText: '2 times/day',
          ),
        ),
        const SizedBox(height: 14),
        TextField(
          controller: durationController,
          decoration: const InputDecoration(
            labelText: 'Duration (optional)',
            hintText: '5 days',
            prefixIcon: Icon(Icons.calendar_month_rounded),
          ),
        ),
        const SizedBox(height: 14),
        TextField(
          controller: medicineInstructionsController,
          maxLines: 2,
          decoration: const InputDecoration(
            labelText: 'Instructions (optional)',
            hintText: 'After meals / before meals',
            alignLabelWithHint: true,
          ),
        ),
        const SizedBox(height: 14),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton.icon(
            key: const Key('add-manual-medicine'),
            onPressed: _isConfirming ? null : _addMedicine,
            icon: const Icon(Icons.add_rounded),
            label: const Text('Add medicine for review'),
          ),
        ),
      ],
    );
  }
}

class _ReviewMedicine {
  final int key;
  final bool fromExtraction;
  PrescriptionMedicineCandidate candidate;

  _ReviewMedicine({
    required this.key,
    required this.candidate,
    required this.fromExtraction,
  });
}

class _IntroCard extends StatelessWidget {
  const _IntroCard();

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const CircleAvatar(
            backgroundColor: AppColors.mint,
            child: Icon(Icons.receipt_long_rounded, color: AppColors.primary),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Text(
              'Upload a prescription, use OCR to suggest medicines, then review and confirm every field. OCR suggestions are never saved automatically.',
              style: TextStyle(
                height: 1.55,
                fontWeight: FontWeight.w600,
                color: AppColors.textDark,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _MedicineReviewCard extends StatefulWidget {
  final int index;
  final _ReviewMedicine medicine;
  final ValueChanged<PrescriptionMedicineCandidate> onChanged;
  final VoidCallback onDelete;

  const _MedicineReviewCard({
    super.key,
    required this.index,
    required this.medicine,
    required this.onChanged,
    required this.onDelete,
  });

  @override
  State<_MedicineReviewCard> createState() => _MedicineReviewCardState();
}

class _MedicineReviewCardState extends State<_MedicineReviewCard> {
  late final TextEditingController _name;
  late final TextEditingController _strength;
  late final TextEditingController _dosage;
  late final TextEditingController _frequency;
  late final TextEditingController _duration;
  late final TextEditingController _instructions;

  @override
  void initState() {
    super.initState();
    final candidate = widget.medicine.candidate;
    _name = TextEditingController(text: candidate.name);
    _strength = TextEditingController(text: candidate.strength);
    _dosage = TextEditingController(text: candidate.dosage);
    _frequency = TextEditingController(text: candidate.frequency);
    _duration = TextEditingController(text: candidate.duration);
    _instructions = TextEditingController(text: candidate.instructions);
  }

  @override
  void dispose() {
    _name.dispose();
    _strength.dispose();
    _dosage.dispose();
    _frequency.dispose();
    _duration.dispose();
    _instructions.dispose();
    super.dispose();
  }

  void _emit() {
    final original = widget.medicine.candidate;
    widget.onChanged(
      original.copyWith(
        name: _name.text,
        strength: _strength.text,
        dosage: _dosage.text,
        frequency: _frequency.text,
        duration: _duration.text,
        instructions: _instructions.text,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final candidate = widget.medicine.candidate;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: AppCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                CircleAvatar(
                  backgroundColor: AppColors.secondary.withValues(alpha: 0.15),
                  child: Text('${widget.index + 1}'),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    widget.medicine.fromExtraction
                        ? candidate.confidence.label
                        : 'Manual entry',
                    style: TextStyle(
                      fontWeight: FontWeight.w700,
                      color: AppColors.primary,
                    ),
                  ),
                ),
                IconButton(
                  key: ValueKey('delete-medicine-${widget.medicine.key}'),
                  tooltip: 'Remove medicine',
                  onPressed: widget.onDelete,
                  icon: const Icon(
                    Icons.delete_outline_rounded,
                    color: AppColors.danger,
                  ),
                ),
              ],
            ),
            if (widget.medicine.fromExtraction &&
                candidate.sourceLine.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                'Source: ${candidate.sourceLine}',
                style: TextStyle(fontSize: 12, color: AppColors.textSoft),
              ),
            ],
            if (candidate.warnings.isNotEmpty) ...[
              const SizedBox(height: 8),
              ...candidate.warnings.map(
                (warning) => Text(
                  '• $warning',
                  style: TextStyle(fontSize: 12, color: AppColors.warning),
                ),
              ),
            ],
            const SizedBox(height: 12),
            TextField(
              key: ValueKey('medicine-${widget.medicine.key}-name'),
              controller: _name,
              onChanged: (_) => _emit(),
              decoration: const InputDecoration(labelText: 'Medicine name'),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _strength,
              onChanged: (_) => _emit(),
              decoration: const InputDecoration(labelText: 'Strength'),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _dosage,
              onChanged: (_) => _emit(),
              decoration: const InputDecoration(labelText: 'Dose amount'),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _frequency,
              onChanged: (_) => _emit(),
              decoration: const InputDecoration(labelText: 'Frequency'),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _duration,
              onChanged: (_) => _emit(),
              decoration: const InputDecoration(labelText: 'Duration'),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _instructions,
              onChanged: (_) => _emit(),
              maxLines: 2,
              decoration: const InputDecoration(labelText: 'Instructions'),
            ),
          ],
        ),
      ),
    );
  }
}

class _ProgressAction extends StatelessWidget {
  final bool busy;
  final String label;
  final IconData icon;
  final VoidCallback onPressed;

  const _ProgressAction({
    required this.busy,
    required this.label,
    required this.icon,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    if (busy) return const Center(child: CircularProgressIndicator());
    return PrimaryButton(text: label, icon: icon, onPressed: onPressed);
  }
}

class _UploadedNotice extends StatelessWidget {
  final int prescriptionId;

  const _UploadedNotice({required this.prescriptionId});

  @override
  Widget build(BuildContext context) {
    return _ReviewNotice(
      icon: Icons.cloud_done_rounded,
      message:
          'Prescription #$prescriptionId is stored. Its image cannot be replaced from this review flow.',
    );
  }
}

class _ReviewNotice extends StatelessWidget {
  final IconData icon;
  final String message;

  const _ReviewNotice({required this.icon, required this.message});

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: AppColors.primary),
          const SizedBox(width: 12),
          Expanded(child: Text(message)),
        ],
      ),
    );
  }
}

class _WarningBox extends StatelessWidget {
  final String message;

  const _WarningBox({required this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.warning.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.warning.withValues(alpha: 0.4)),
      ),
      child: Text(message),
    );
  }
}
