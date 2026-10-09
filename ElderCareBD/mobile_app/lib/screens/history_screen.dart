import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../models/model_prediction.dart';
import '../services/api_service.dart';
import '../services/session_service.dart';
import '../utils/app_colors.dart';
import '../utils/app_strings.dart';
import '../utils/assessment_history_utils.dart';
import '../utils/input_validation.dart';
import '../widgets/app_card.dart';
import '../widgets/responsive_content.dart';

class HistoryScreen extends StatefulWidget {
  const HistoryScreen({super.key});

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  bool isLoading = true;
  String? errorMessage;

  int? patientId;
  String patientName = 'Selected Patient';

  List<dynamic> assessments = [];
  List<dynamic> prescriptions = [];
  List<dynamic> medicines = [];

  @override
  void initState() {
    super.initState();
    _loadFullHistory();
  }

  Future<void> _loadFullHistory() async {
    setState(() {
      isLoading = true;
      errorMessage = null;
    });

    try {
      final savedPatientId = await SessionService.getSelectedPatientId();
      final savedPatientName = await SessionService.getSelectedPatientName();

      if (savedPatientId == null) {
        setState(() {
          isLoading = false;
          errorMessage = 'Please save or select a patient profile first.';
        });
        return;
      }

      final assessmentData = await ApiService.getPatientAssessments(
        patientId: savedPatientId,
      );

      final prescriptionData = await ApiService.getPatientPrescriptions(
        patientId: savedPatientId,
      );

      final medicineData = await ApiService.getPatientMedicines(
        patientId: savedPatientId,
      );

      setState(() {
        patientId = savedPatientId;
        patientName = savedPatientName ?? 'Selected Patient';

        assessments = assessmentData;
        prescriptions = prescriptionData.reversed.toList();
        medicines = medicineData.reversed.toList();

        isLoading = false;
      });
    } catch (_) {
      setState(() {
        isLoading = false;
        errorMessage =
            'Could not load history. Check your connection and try again.';
      });
    }
  }

  String _formatDate(dynamic rawDate) {
    if (rawDate == null || rawDate.toString().isEmpty) {
      return 'Not available';
    }

    try {
      final date = DateTime.parse(rawDate.toString());
      return DateFormat('dd MMM yyyy, hh:mm a').format(date);
    } catch (_) {
      return rawDate.toString();
    }
  }

  String _formatAssessmentDate(dynamic rawDate) {
    return formatAssessmentTimestamp(rawDate);
  }

  String _formatOnlyDate(dynamic rawDate) {
    if (rawDate == null || rawDate.toString().isEmpty) {
      return 'Not available';
    }

    try {
      final date = DateTime.parse(rawDate.toString());
      return DateFormat('dd MMM yyyy').format(date);
    } catch (_) {
      return rawDate.toString();
    }
  }

  Color _riskColor(String risk) {
    if (risk == 'High') return AppColors.danger;
    if (risk == 'Medium') return AppColors.warning;
    if (risk == 'Low') return AppColors.success;
    return AppColors.primary;
  }

  int? _remainingDays(dynamic rawRunOutDate) {
    if (rawRunOutDate == null || rawRunOutDate.toString().isEmpty) {
      return null;
    }

    try {
      final date = DateTime.parse(rawRunOutDate.toString());
      return date.difference(DateTime.now()).inDays;
    } catch (_) {
      return null;
    }
  }

  @override
  Widget build(BuildContext context) {
    final strings = AppStrings.of(context);
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: Text(strings.history),
          actions: [
            IconButton(
              onPressed: _loadFullHistory,
              tooltip: strings.retry,
              icon: const Icon(Icons.refresh_rounded),
            ),
          ],
          bottom: const TabBar(
            tabs: [
              Tab(icon: Icon(Icons.monitor_heart_rounded), text: 'Assessments'),
              Tab(
                icon: Icon(Icons.receipt_long_rounded),
                text: 'Prescriptions',
              ),
              Tab(icon: Icon(Icons.medication_rounded), text: 'Medicines'),
            ],
          ),
        ),
        body: isLoading
            ? Center(
                child: Semantics(
                  label: 'Loading health history',
                  liveRegion: true,
                  child: const CircularProgressIndicator(),
                ),
              )
            : errorMessage != null
            ? _ErrorView(message: errorMessage!, onRetry: _loadFullHistory)
            : ResponsiveContent(
                padding: EdgeInsets.zero,
                fillHeight: true,
                child: Column(
                  children: [
                    _HistorySummaryHeader(
                      patientName: patientName,
                      patientId: patientId,
                      assessmentCount: assessments.length,
                      prescriptionCount: prescriptions.length,
                      medicineCount: medicines.length,
                    ),
                    Expanded(
                      child: TabBarView(
                        children: [
                          _AssessmentHistoryTab(
                            assessments: assessments,
                            formatDate: _formatAssessmentDate,
                            riskColor: _riskColor,
                          ),
                          _PrescriptionHistoryTab(
                            prescriptions: prescriptions,
                            formatDate: _formatDate,
                          ),
                          _MedicineHistoryTab(
                            medicines: medicines,
                            formatDate: _formatOnlyDate,
                            remainingDays: _remainingDays,
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
      ),
    );
  }
}

class _HistorySummaryHeader extends StatelessWidget {
  final String patientName;
  final int? patientId;
  final int assessmentCount;
  final int prescriptionCount;
  final int medicineCount;

  const _HistorySummaryHeader({
    required this.patientName,
    required this.patientId,
    required this.assessmentCount,
    required this.prescriptionCount,
    required this.medicineCount,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.all(16),
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        color: AppColors.primaryDark,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            patientId == null
                ? patientName
                : '$patientName • Patient ID: $patientId',
            style: TextStyle(
              color: Colors.white,
              fontSize: 20,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'Complete saved care history from FastAPI backend and SQLite database.',
            style: TextStyle(
              color: Colors.white.withValues(alpha: 0.86),
              height: 1.45,
              fontWeight: FontWeight.w500,
            ),
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              _HeaderStat(label: 'Assessments', value: assessmentCount),
              const SizedBox(width: 8),
              _HeaderStat(label: 'Prescriptions', value: prescriptionCount),
              const SizedBox(width: 8),
              _HeaderStat(label: 'Medicines', value: medicineCount),
            ],
          ),
        ],
      ),
    );
  }
}

class _HeaderStat extends StatelessWidget {
  final String label;
  final int value;

  const _HeaderStat({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 8),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.14),
          borderRadius: BorderRadius.circular(16),
        ),
        child: Column(
          children: [
            Text(
              value.toString(),
              style: TextStyle(
                color: Colors.white,
                fontSize: 18,
                fontWeight: FontWeight.w900,
              ),
            ),
            const SizedBox(height: 3),
            Text(
              label,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: Colors.white70,
                fontSize: 10.5,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AssessmentHistoryTab extends StatelessWidget {
  final List<dynamic> assessments;
  final String Function(dynamic) formatDate;
  final Color Function(String) riskColor;

  const _AssessmentHistoryTab({
    required this.assessments,
    required this.formatDate,
    required this.riskColor,
  });

  @override
  Widget build(BuildContext context) {
    if (assessments.isEmpty) {
      return const _EmptyView(
        icon: Icons.monitor_heart_rounded,
        title: 'No assessment history found',
        subtitle:
            'Complete a health assessment first. Saved results will appear here.',
      );
    }

    final heartRecords = _heartModelRecords(assessments);
    final summaryOffset = heartRecords.isEmpty ? 0 : 1;

    return ListView.builder(
      padding: const EdgeInsets.fromLTRB(16, 6, 16, 20),
      itemCount: assessments.length + summaryOffset,
      itemBuilder: (context, index) {
        if (summaryOffset == 1 && index == 0) {
          return Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: _WeeklyHeartScreeningSummary(records: heartRecords),
          );
        }

        final assessmentIndex = index - summaryOffset;
        final item = Map<String, dynamic>.from(assessments[assessmentIndex]);

        final overallRisk = item['overall_risk']?.toString() ?? 'N/A';
        final diabetesRisk = item['diabetes_risk']?.toString() ?? 'N/A';
        final heartRisk = item['heart_risk']?.toString() ?? 'N/A';
        final diabetesPrediction = DiseasePrediction.fromAssessmentHistory(
          item,
          'diabetes',
        );
        final heartPrediction = DiseasePrediction.fromAssessmentHistory(
          item,
          'heart',
        );
        final heightCm = item['height_cm'];
        final weightKg = item['weight_kg'];
        final note = item['note']?.toString();
        final symptoms = activeAssessmentSymptomLabels(item);
        final color = riskColor(overallRisk);

        return Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: AppCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    CircleAvatar(
                      backgroundColor: color.withValues(alpha: 0.12),
                      child: Icon(
                        Icons.health_and_safety_rounded,
                        color: color,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        'Assessment #${item['id'] ?? assessmentIndex + 1}',
                        style: TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w900,
                          color: AppColors.textDark,
                        ),
                      ),
                    ),
                    _Badge(text: overallRisk, color: color),
                  ],
                ),
                const SizedBox(height: 14),

                _InfoRow(title: 'Date', value: formatDate(item['created_at'])),
                _InfoRow(title: 'Age', value: item['age']?.toString() ?? 'N/A'),
                _InfoRow(
                  title: 'Glucose',
                  value: InputValidation.formatStoredGlucoseMmolL(
                    item['glucose'],
                  ),
                ),
                _InfoRow(
                  title: 'Blood Pressure',
                  value:
                      '${item['systolic_bp'] ?? 'N/A'}/${item['diastolic_bp'] ?? 'N/A'}',
                ),
                _InfoRow(title: 'BMI', value: item['bmi']?.toString() ?? 'N/A'),
                if (heightCm != null)
                  _InfoRow(title: 'Height', value: '$heightCm cm'),
                if (weightKg != null)
                  _InfoRow(title: 'Weight', value: '$weightKg kg'),
                _InfoRow(
                  title: 'Symptoms',
                  value: symptoms.isEmpty
                      ? 'No recorded symptoms'
                      : symptoms.join(' \u2022 '),
                ),
                if (note != null && note.trim().isNotEmpty)
                  _InfoRow(title: 'Caregiver note', value: note),
                _InfoRow(
                  title: 'General screening',
                  value: '$overallRisk (demo heuristic)',
                ),
                const SizedBox(height: 6),
                _AssessmentDiseasePredictionHistory(
                  title: 'Diabetes screening',
                  historicalHeuristicRisk: diabetesRisk,
                  prediction: diabetesPrediction,
                ),
                const SizedBox(height: 10),
                _AssessmentDiseasePredictionHistory(
                  title: 'Heart screening',
                  historicalHeuristicRisk: heartRisk,
                  prediction: heartPrediction,
                ),

                const SizedBox(height: 10),

                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(13),
                  decoration: BoxDecoration(
                    color: AppColors.mint,
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Text(
                    item['recommendation']?.toString() ??
                        'No recommendation saved.',
                    style: TextStyle(
                      color: AppColors.textDark,
                      height: 1.45,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  List<_HeartScreeningRecord> _heartModelRecords(List<dynamic> source) {
    final records = <_HeartScreeningRecord>[];
    for (final raw in source) {
      final item = Map<String, dynamic>.from(raw);
      final prediction = DiseasePrediction.fromAssessmentHistory(item, 'heart');
      final timestamp = DateTime.tryParse(item['created_at']?.toString() ?? '');
      if (prediction?.isModelPrediction != true || timestamp == null) continue;
      records.add(
        _HeartScreeningRecord(
          timestamp: timestamp,
          score: prediction!.riskScore!,
        ),
      );
    }
    records.sort((a, b) => b.timestamp.compareTo(a.timestamp));
    return records;
  }
}

class _HeartScreeningRecord {
  final DateTime timestamp;
  final double score;

  const _HeartScreeningRecord({required this.timestamp, required this.score});
}

class _WeeklyHeartScreeningSummary extends StatelessWidget {
  final List<_HeartScreeningRecord> records;

  const _WeeklyHeartScreeningSummary({required this.records});

  @override
  Widget build(BuildContext context) {
    final latest = records.first;
    final windowEnd = DateTime(
      latest.timestamp.year,
      latest.timestamp.month,
      latest.timestamp.day,
    );
    final windowStart = windowEnd.subtract(const Duration(days: 6));
    final weeklyRecords = records
        .where((record) {
          final day = DateTime(
            record.timestamp.year,
            record.timestamp.month,
            record.timestamp.day,
          );
          return !day.isBefore(windowStart) && !day.isAfter(windowEnd);
        })
        .toList(growable: false);
    final scores = weeklyRecords.map((record) => record.score).toList();
    final minimum = scores.reduce((a, b) => a < b ? a : b);
    final maximum = scores.reduce((a, b) => a > b ? a : b);
    final dateFormat = DateFormat('dd MMM');

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const CircleAvatar(
                backgroundColor: AppColors.mint,
                child: Icon(Icons.show_chart_rounded, color: AppColors.primary),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  'Weekly Heart v2 screening record',
                  style: TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w900,
                    color: AppColors.textDark,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            'Latest model score: ${(latest.score * 100).toStringAsFixed(1)}%',
            style: TextStyle(
              color: AppColors.primary,
              fontSize: 18,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 5),
          Text(
            '${weeklyRecords.length} saved screening${weeklyRecords.length == 1 ? '' : 's'} from ${dateFormat.format(windowStart)} to ${dateFormat.format(windowEnd)}. '
            'Recorded range: ${(minimum * 100).toStringAsFixed(1)}%–${(maximum * 100).toStringAsFixed(1)}%.',
            style: TextStyle(color: AppColors.textSoft, height: 1.45),
          ),
          const SizedBox(height: 8),
          Text(
            'This is a trend of saved, non-diagnostic heart-disease screening scores. It does not forecast an acute heart attack.',
            style: TextStyle(
              color: AppColors.warning,
              fontWeight: FontWeight.w700,
              height: 1.4,
            ),
          ),
        ],
      ),
    );
  }
}

class _AssessmentDiseasePredictionHistory extends StatelessWidget {
  final String title;
  final String historicalHeuristicRisk;
  final DiseasePrediction? prediction;

  const _AssessmentDiseasePredictionHistory({
    required this.title,
    required this.historicalHeuristicRisk,
    required this.prediction,
  });

  @override
  Widget build(BuildContext context) {
    final savedPrediction = prediction;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.mint,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: TextStyle(
              color: AppColors.textDark,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 5),
          if (savedPrediction?.predictionStatus ==
              'not_applicable_known_diabetes') ...[
            Text(
              'Screening not applicable',
              style: TextStyle(
                color: AppColors.primary,
                fontWeight: FontWeight.w800,
              ),
            ),
            Text(
              savedPrediction!.fallbackMessage,
              style: TextStyle(color: AppColors.textSoft),
            ),
          ] else if (savedPrediction?.isModelPrediction == true) ...[
            Text(
              savedPrediction!.modelDisplayLabel,
              style: TextStyle(
                color: AppColors.primary,
                fontWeight: FontWeight.w800,
              ),
            ),
            Text(
              'Screening-model score: ${savedPrediction.riskScore!.toStringAsFixed(2)}',
              style: TextStyle(color: AppColors.textDark),
            ),
            Text(
              savedPrediction.classificationLabel,
              style: TextStyle(color: AppColors.textDark),
            ),
            Text(
              'Version ${savedPrediction.modelVersion} - screening threshold ${savedPrediction.threshold!.toStringAsFixed(2)}',
              style: TextStyle(color: AppColors.textSoft),
            ),
          ] else if (savedPrediction == null) ...[
            Text(
              'Historical demo heuristic: $historicalHeuristicRisk',
              style: TextStyle(
                color: AppColors.textDark,
                fontWeight: FontWeight.w700,
              ),
            ),
            Text(
              'This assessment predates stored model provenance.',
              style: TextStyle(color: AppColors.textSoft),
            ),
          ] else ...[
            Text(
              'Heuristic demo fallback: $historicalHeuristicRisk',
              style: TextStyle(
                color: AppColors.textDark,
                fontWeight: FontWeight.w700,
              ),
            ),
            Text(
              savedPrediction.fallbackMessage,
              style: TextStyle(color: AppColors.textSoft),
            ),
          ],
        ],
      ),
    );
  }
}

class _PrescriptionHistoryTab extends StatelessWidget {
  final List<dynamic> prescriptions;
  final String Function(dynamic) formatDate;

  const _PrescriptionHistoryTab({
    required this.prescriptions,
    required this.formatDate,
  });

  String _statusLabel(Object? value) {
    return switch (value?.toString().trim().toLowerCase()) {
      'uploaded' => 'Uploaded',
      'processing' => 'Processing',
      'ready' => 'Ready for review',
      'failed' => 'OCR failed',
      'confirmed' => 'Confirmed',
      _ => 'Not processed',
    };
  }

  Color _statusColor(Object? value) {
    return switch (value?.toString().trim().toLowerCase()) {
      'confirmed' => AppColors.success,
      'failed' => AppColors.danger,
      'processing' => AppColors.warning,
      _ => AppColors.primary,
    };
  }

  @override
  Widget build(BuildContext context) {
    if (prescriptions.isEmpty) {
      return const _EmptyView(
        icon: Icons.receipt_long_rounded,
        title: 'No prescription history found',
        subtitle:
            'Add a prescription first. Saved prescriptions will appear here.',
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.fromLTRB(16, 6, 16, 20),
      itemCount: prescriptions.length,
      itemBuilder: (context, index) {
        final item = Map<String, dynamic>.from(prescriptions[index]);

        final doctorName = item['doctor_name']?.toString();
        final note = item['note']?.toString();
        final hasImage = item['has_image'] == true;
        final ocrStatus = item['ocr_status'];
        final rawMedicines = item['medicines'];
        final prescriptionMedicines = rawMedicines is List
            ? rawMedicines
                  .whereType<Map>()
                  .map(Map<String, dynamic>.from)
                  .toList()
            : <Map<String, dynamic>>[];
        final rawPrescriptionId = item['id'];
        final prescriptionId = rawPrescriptionId is int
            ? rawPrescriptionId
            : int.tryParse(rawPrescriptionId?.toString() ?? '');

        return Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: AppCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const CircleAvatar(
                      backgroundColor: AppColors.mint,
                      child: Icon(
                        Icons.receipt_long_rounded,
                        color: AppColors.primary,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        'Prescription #${item['id'] ?? index + 1}',
                        style: TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w900,
                          color: AppColors.textDark,
                        ),
                      ),
                    ),
                    _Badge(
                      text: _statusLabel(ocrStatus),
                      color: _statusColor(ocrStatus),
                    ),
                  ],
                ),
                const SizedBox(height: 14),

                _InfoRow(title: 'Date', value: formatDate(item['created_at'])),
                _InfoRow(
                  title: 'Doctor',
                  value:
                      doctorName == null ||
                          doctorName == 'null' ||
                          doctorName.isEmpty
                      ? 'Not added'
                      : doctorName,
                ),
                _InfoRow(
                  title: 'Note',
                  value: note == null || note == 'null' || note.isEmpty
                      ? 'No note added'
                      : note,
                ),
                _InfoRow(
                  title: 'Image',
                  value: hasImage ? 'Stored securely' : 'No image uploaded',
                ),
                _InfoRow(title: 'OCR status', value: _statusLabel(ocrStatus)),
                if (hasImage && prescriptionId != null) ...[
                  const SizedBox(height: 10),
                  _ProtectedPrescriptionImage(prescriptionId: prescriptionId),
                ],
                const SizedBox(height: 16),
                Text(
                  'Confirmed medicines (${prescriptionMedicines.length})',
                  style: TextStyle(
                    fontWeight: FontWeight.w800,
                    color: AppColors.textDark,
                  ),
                ),
                const SizedBox(height: 8),
                if (prescriptionMedicines.isEmpty)
                  Text(
                    'No confirmed medicine details are available for this prescription.',
                    style: TextStyle(color: AppColors.textSoft),
                  )
                else
                  ...prescriptionMedicines.map(
                    (medicine) =>
                        _PrescriptionMedicineSummary(medicine: medicine),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _PrescriptionMedicineSummary extends StatelessWidget {
  final Map<String, dynamic> medicine;

  const _PrescriptionMedicineSummary({required this.medicine});

  String? _available(Object? value) {
    if (value == null) return null;
    final text = value.toString().trim();
    return text.isEmpty || text.toLowerCase() == 'null' ? null : text;
  }

  @override
  Widget build(BuildContext context) {
    final name = _available(medicine['name']) ?? 'Unknown medicine';
    final details = <MapEntry<String, String>>[
      if (_available(medicine['strength']) case final value?)
        MapEntry('Strength', value),
      if (_available(medicine['dosage']) case final value?)
        MapEntry('Dose amount', value),
      if (_available(medicine['frequency']) case final value?)
        MapEntry('Frequency', value),
      if (_available(medicine['duration']) case final value?)
        MapEntry('Duration', value),
      if (_available(medicine['instructions']) case final value?)
        MapEntry('Instructions', value),
    ];

    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.mint,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            name,
            style: TextStyle(
              fontWeight: FontWeight.w800,
              color: AppColors.textDark,
            ),
          ),
          if (details.isNotEmpty) const SizedBox(height: 5),
          ...details.map(
            (detail) => Text(
              '${detail.key}: ${detail.value}',
              style: TextStyle(color: AppColors.textSoft, height: 1.4),
            ),
          ),
        ],
      ),
    );
  }
}

class _ProtectedPrescriptionImage extends StatefulWidget {
  final int prescriptionId;

  const _ProtectedPrescriptionImage({required this.prescriptionId});

  @override
  State<_ProtectedPrescriptionImage> createState() =>
      _ProtectedPrescriptionImageState();
}

class _ProtectedPrescriptionImageState
    extends State<_ProtectedPrescriptionImage> {
  late Future<Uint8List> _imageFuture;

  @override
  void initState() {
    super.initState();
    _imageFuture = _loadImage();
  }

  @override
  void didUpdateWidget(covariant _ProtectedPrescriptionImage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.prescriptionId != widget.prescriptionId) {
      _imageFuture = _loadImage();
    }
  }

  Future<Uint8List> _loadImage() {
    return ApiService.getPrescriptionImage(
      prescriptionId: widget.prescriptionId,
    );
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Uint8List>(
      future: _imageFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const SizedBox(
            height: 120,
            child: Center(child: CircularProgressIndicator()),
          );
        }

        final bytes = snapshot.data;
        if (snapshot.hasError || bytes == null || bytes.isEmpty) {
          return Container(
            height: 96,
            width: double.infinity,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: AppColors.mint,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: AppColors.border),
            ),
            child: Text(
              'Prescription image unavailable',
              style: TextStyle(
                color: AppColors.textSoft,
                fontWeight: FontWeight.w600,
              ),
            ),
          );
        }

        return Semantics(
          button: true,
          label: 'Open prescription image',
          child: InkWell(
            borderRadius: BorderRadius.circular(14),
            onTap: () {
              showDialog<void>(
                context: context,
                builder: (dialogContext) => Dialog(
                  child: InteractiveViewer(
                    minScale: 0.8,
                    maxScale: 4,
                    child: Image.memory(
                      bytes,
                      fit: BoxFit.contain,
                      errorBuilder: (context, error, stackTrace) =>
                          const Padding(
                            padding: EdgeInsets.all(24),
                            child: Text('Prescription image unavailable'),
                          ),
                    ),
                  ),
                ),
              );
            },
            child: ClipRRect(
              borderRadius: BorderRadius.circular(14),
              child: Image.memory(
                bytes,
                height: 180,
                width: double.infinity,
                fit: BoxFit.cover,
                errorBuilder: (context, error, stackTrace) => const SizedBox(
                  height: 96,
                  child: Center(child: Text('Prescription image unavailable')),
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

class _MedicineHistoryTab extends StatelessWidget {
  final List<dynamic> medicines;
  final String Function(dynamic) formatDate;
  final int? Function(dynamic) remainingDays;

  const _MedicineHistoryTab({
    required this.medicines,
    required this.formatDate,
    required this.remainingDays,
  });

  Color _medicineColor(int? days) {
    if (days == null) return AppColors.primary;
    if (days <= 3) return AppColors.danger;
    if (days <= 7) return AppColors.warning;
    return AppColors.success;
  }

  String _medicineStatus(int? days) {
    if (days == null) return 'Saved';
    if (days <= 0) return 'May be finished';
    if (days <= 3) return 'Urgent';
    if (days <= 7) return 'Restock soon';
    return 'Available';
  }

  @override
  Widget build(BuildContext context) {
    if (medicines.isEmpty) {
      return const _EmptyView(
        icon: Icons.medication_rounded,
        title: 'No medicine history found',
        subtitle:
            'Add medicine from prescription or tracker. Saved medicines will appear here.',
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.fromLTRB(16, 6, 16, 20),
      itemCount: medicines.length,
      itemBuilder: (context, index) {
        final item = Map<String, dynamic>.from(medicines[index]);

        final days = remainingDays(item['run_out_date']);
        final color = _medicineColor(days);

        final dosage = item['dosage']?.toString();
        final frequency = item['frequency']?.toString();

        return Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: AppCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    CircleAvatar(
                      backgroundColor: color.withValues(alpha: 0.12),
                      child: Icon(Icons.medication_rounded, color: color),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        item['name']?.toString() ?? 'Unknown medicine',
                        style: TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w900,
                          color: AppColors.textDark,
                        ),
                      ),
                    ),
                    _Badge(text: _medicineStatus(days), color: color),
                  ],
                ),
                const SizedBox(height: 14),

                if (dosage != null && dosage != 'null' && dosage.isNotEmpty)
                  _InfoRow(title: 'Dosage', value: dosage),
                if (frequency != null &&
                    frequency != 'null' &&
                    frequency.isNotEmpty)
                  _InfoRow(title: 'Frequency', value: frequency),

                _InfoRow(
                  title: 'Quantity',
                  value: item['quantity']?.toString() ?? 'N/A',
                ),
                _InfoRow(
                  title: 'Daily Dose',
                  value: item['daily_dose']?.toString() ?? 'N/A',
                ),
                _InfoRow(
                  title: 'Start Date',
                  value: formatDate(item['start_date']),
                ),
                _InfoRow(
                  title: 'Run-out Date',
                  value: formatDate(item['run_out_date']),
                ),
                _InfoRow(
                  title: 'Alert Date',
                  value: formatDate(item['alert_date']),
                ),

                const SizedBox(height: 10),

                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(13),
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.08),
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Text(
                    days == null
                        ? 'This medicine was saved successfully.'
                        : days <= 0
                        ? 'This medicine may already be finished. Please review stock.'
                        : 'Estimated remaining: $days day(s).',
                    style: TextStyle(
                      color: color,
                      height: 1.45,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _InfoRow extends StatelessWidget {
  final String title;
  final String value;

  const _InfoRow({required this.title, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 7),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 118,
            child: Text(
              title,
              style: TextStyle(
                color: AppColors.textSoft,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: TextStyle(
                color: AppColors.textDark,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  final String text;
  final Color color;

  const _Badge({required this.text, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(99),
      ),
      child: Text(
        text,
        style: TextStyle(
          color: color,
          fontSize: 11,
          fontWeight: FontWeight.w900,
        ),
      ),
    );
  }
}

class _EmptyView extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;

  const _EmptyView({
    required this.icon,
    required this.title,
    required this.subtitle,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: AppCard(
          padding: const EdgeInsets.all(26),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 60, color: AppColors.primary),
              const SizedBox(height: 14),
              Text(
                title,
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w900,
                  color: AppColors.textDark,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                subtitle,
                textAlign: TextAlign.center,
                style: TextStyle(color: AppColors.textSoft, height: 1.45),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ErrorView extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;

  const _ErrorView({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: AppCard(
          padding: const EdgeInsets.all(26),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(
                Icons.error_outline_rounded,
                size: 60,
                color: AppColors.danger,
              ),
              const SizedBox(height: 14),
              Text(
                message,
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: AppColors.textDark,
                  height: 1.45,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 16),
              OutlinedButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh_rounded),
                label: const Text('Try Again'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
