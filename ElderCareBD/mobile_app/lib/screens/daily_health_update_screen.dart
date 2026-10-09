import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../models/daily_observation.dart';
import '../services/api_service.dart';
import '../services/session_service.dart';
import '../utils/app_colors.dart';
import '../utils/app_spacing.dart';
import '../widgets/app_card.dart';
import '../widgets/primary_button.dart';
import '../widgets/responsive_content.dart';
import '../widgets/section_header.dart';

typedef TodayObservationLoader =
    Future<DailyObservation?> Function(int patientId);
typedef TodayObservationCreator =
    Future<DailyObservation> Function(
      int patientId,
      DailyObservationDraft observation,
    );
typedef ObservationUpdater =
    Future<DailyObservation> Function(
      int patientId,
      int observationId,
      DailyObservationDraft observation,
    );
typedef SelectedPatientIdLoader = Future<int?> Function();
typedef SelectedPatientNameLoader = Future<String?> Function();

class DailyHealthUpdateScreen extends StatefulWidget {
  const DailyHealthUpdateScreen({
    super.key,
    this.observationLoader,
    this.observationCreator,
    this.observationUpdater,
    this.patientIdLoader,
    this.patientNameLoader,
  });

  final TodayObservationLoader? observationLoader;
  final TodayObservationCreator? observationCreator;
  final ObservationUpdater? observationUpdater;
  final SelectedPatientIdLoader? patientIdLoader;
  final SelectedPatientNameLoader? patientNameLoader;

  @override
  State<DailyHealthUpdateScreen> createState() =>
      _DailyHealthUpdateScreenState();
}

class _DailyHealthUpdateScreenState extends State<DailyHealthUpdateScreen> {
  final _formKey = GlobalKey<FormState>();
  final _systolic = TextEditingController();
  final _diastolic = TextEditingController();
  final _spo2 = TextEditingController();
  final _pulse = TextEditingController();
  final _weight = TextEditingController();
  final _temperature = TextEditingController();
  final _glucose = TextEditingController();
  final _symptoms = TextEditingController();
  final _notes = TextEditingController();

  int? _patientId;
  String _patientName = 'Selected patient';
  DailyObservation? _observation;
  String? _glucoseUnit;
  String? _temperatureUnit;
  String? _glucoseContext;
  String? _feedback;
  bool _feedbackIsError = false;
  bool _loading = true;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final controller in [
      _systolic,
      _diastolic,
      _spo2,
      _pulse,
      _weight,
      _temperature,
      _glucose,
      _symptoms,
      _notes,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    if (mounted) {
      setState(() {
        _loading = true;
        _feedback = null;
      });
    }
    try {
      final idLoader =
          widget.patientIdLoader ?? SessionService.getSelectedPatientId;
      final nameLoader =
          widget.patientNameLoader ?? SessionService.getSelectedPatientName;
      final patientId = await idLoader();
      final patientName = await nameLoader();
      if (!mounted) return;
      if (patientId == null) {
        setState(() {
          _patientId = null;
          _loading = false;
          _feedbackIsError = true;
          _feedback =
              'Select a patient from the caregiver dashboard before recording an update.';
        });
        return;
      }
      final loader =
          widget.observationLoader ??
          (id) => ApiService.getTodayObservation(patientId: id);
      final observation = await loader(patientId);
      if (!mounted) return;
      setState(() {
        _patientId = patientId;
        _patientName = patientName?.trim().isNotEmpty == true
            ? patientName!.trim()
            : 'Selected patient';
        _observation = observation;
        _populate(observation);
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _feedbackIsError = true;
        _feedback = _messageFor(error);
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _feedbackIsError = true;
        _feedback = 'Could not load today\'s health update. Please try again.';
      });
    }
  }

  void _populate(DailyObservation? observation) {
    final values = observation?.values;
    _systolic.text = _format(values?.systolicBp);
    _diastolic.text = _format(values?.diastolicBp);
    _spo2.text = _format(values?.spo2Percent);
    _pulse.text = _format(values?.pulseBpm);
    _weight.text = _format(values?.weightKg);
    _temperature.text = _format(values?.temperatureValue);
    _glucose.text = _format(values?.glucoseValue);
    _symptoms.text = values?.symptoms ?? '';
    _notes.text = values?.notes ?? '';
    _glucoseUnit = values?.glucoseUnit;
    _temperatureUnit = values?.temperatureUnit;
    _glucoseContext = values?.glucoseContext;
  }

  String _format(double? value) {
    if (value == null) return '';
    return value == value.roundToDouble()
        ? value.toInt().toString()
        : value.toString();
  }

  String _messageFor(ApiException error) {
    return switch (error.statusCode) {
      401 => 'Your session has expired. Please sign in again.',
      404 =>
        'This patient is unavailable or no longer belongs to your account.',
      _ => error.message,
    };
  }

  double? _number(TextEditingController controller) {
    final text = controller.text.trim();
    return text.isEmpty ? null : double.tryParse(text);
  }

  String? _optionalNumberValidator(
    String? raw, {
    required String label,
    required double minimum,
    required double maximum,
  }) {
    final text = raw?.trim() ?? '';
    if (text.isEmpty) return null;
    final value = double.tryParse(text);
    if (value == null || !value.isFinite) return 'Enter a valid $label.';
    if (value < minimum || value > maximum) {
      return '$label must be between ${_rangeNumber(minimum)} and ${_rangeNumber(maximum)}.';
    }
    return null;
  }

  String _rangeNumber(double value) => value == value.roundToDouble()
      ? value.toInt().toString()
      : value.toString();

  String? _temperatureValidator(String? raw) {
    final text = raw?.trim() ?? '';
    if (text.isEmpty) {
      return _temperatureUnit == null
          ? null
          : 'Enter a temperature or clear the unit.';
    }
    final value = double.tryParse(text);
    if (value == null || !value.isFinite) {
      return 'Enter a valid temperature.';
    }
    if (_temperatureUnit == null) return 'Select C or F.';
    final minimum = _temperatureUnit == 'C' ? 32.0 : 89.6;
    final maximum = _temperatureUnit == 'C' ? 43.0 : 109.4;
    if (value < minimum || value > maximum) {
      return 'Temperature must be ${_rangeNumber(minimum)}–${_rangeNumber(maximum)} $_temperatureUnit.';
    }
    return null;
  }

  String? _glucoseValidator(String? raw) {
    final text = raw?.trim() ?? '';
    if (text.isEmpty) {
      return _glucoseUnit == null ? null : 'Enter glucose or clear the unit.';
    }
    final value = double.tryParse(text);
    if (value == null || !value.isFinite) return 'Enter a valid glucose value.';
    if (_glucoseUnit == null) return 'Select a glucose unit.';
    final minimum = _glucoseUnit == 'mg/dL' ? 20.0 : 1.1;
    final maximum = _glucoseUnit == 'mg/dL' ? 600.0 : 33.3;
    if (value < minimum || value > maximum) {
      return 'Glucose must be ${_rangeNumber(minimum)}–${_rangeNumber(maximum)} $_glucoseUnit.';
    }
    return null;
  }

  bool _hasAnyValue() {
    return [
      _systolic,
      _diastolic,
      _spo2,
      _pulse,
      _weight,
      _temperature,
      _glucose,
      _symptoms,
      _notes,
    ].any((controller) => controller.text.trim().isNotEmpty);
  }

  Future<void> _save() async {
    FocusScope.of(context).unfocus();
    setState(() {
      _feedback = null;
      _feedbackIsError = false;
    });
    if (!(_formKey.currentState?.validate() ?? false)) return;

    final systolic = _number(_systolic);
    final diastolic = _number(_diastolic);
    if (systolic != null && diastolic != null && diastolic >= systolic) {
      setState(() {
        _feedbackIsError = true;
        _feedback = 'Diastolic BP must be lower than systolic BP.';
      });
      return;
    }
    if (!_hasAnyValue()) {
      setState(() {
        _feedbackIsError = true;
        _feedback = 'Enter at least one observation before saving.';
      });
      return;
    }

    final patientId = _patientId;
    if (patientId == null) return;
    final draft = DailyObservationDraft(
      systolicBp: systolic,
      diastolicBp: diastolic,
      glucoseValue: _number(_glucose),
      glucoseUnit: _glucoseUnit,
      glucoseContext: _glucoseContext,
      pulseBpm: _number(_pulse),
      spo2Percent: _number(_spo2),
      temperatureValue: _number(_temperature),
      temperatureUnit: _temperatureUnit,
      weightKg: _number(_weight),
      symptoms: _trimmedOrNull(_symptoms.text),
      notes: _trimmedOrNull(_notes.text),
    );

    setState(() => _saving = true);
    try {
      final existing = _observation;
      final saved = existing == null
          ? await (widget.observationCreator ??
                (id, value) => ApiService.createTodayObservation(
                  patientId: id,
                  observation: value,
                ))(patientId, draft)
          : await (widget.observationUpdater ??
                (id, observationId, value) => ApiService.updateObservation(
                  patientId: id,
                  observationId: observationId,
                  observation: value,
                ))(patientId, existing.id, draft);
      if (!mounted) return;
      setState(() {
        _observation = saved;
        _populate(saved);
        _saving = false;
        _feedbackIsError = false;
        _feedback = 'Today\'s health update was saved successfully.';
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Health update saved successfully.')),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      if (error.statusCode == 409) {
        setState(() {
          _saving = false;
          _feedbackIsError = false;
          _feedback =
              'An update already exists for today. The saved values were reloaded.';
        });
        await _reloadAfterConflict(patientId);
        return;
      }
      setState(() {
        _saving = false;
        _feedbackIsError = true;
        _feedback = _messageFor(error);
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _feedbackIsError = true;
        _feedback = 'Could not connect to the server. Please try again.';
      });
    }
  }

  Future<void> _reloadAfterConflict(int patientId) async {
    try {
      final loader =
          widget.observationLoader ??
          (id) => ApiService.getTodayObservation(patientId: id);
      final saved = await loader(patientId);
      if (!mounted || saved == null) return;
      setState(() {
        _observation = saved;
        _populate(saved);
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _feedbackIsError = true;
        _feedback = _messageFor(error);
      });
    }
  }

  String? _trimmedOrNull(String value) {
    final trimmed = value.trim();
    return trimmed.isEmpty ? null : trimmed;
  }

  TextFormField _measurementField({
    required Key key,
    required TextEditingController controller,
    required String label,
    required String suffix,
    required String? Function(String?) validator,
  }) {
    return TextFormField(
      key: key,
      controller: controller,
      keyboardType: const TextInputType.numberWithOptions(decimal: true),
      inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9.]'))],
      decoration: InputDecoration(labelText: label, suffixText: suffix),
      validator: validator,
    );
  }

  Widget _feedbackBanner() {
    final isError = _feedbackIsError;
    return Container(
      key: const Key('daily-observation-feedback'),
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: (isError ? AppColors.danger : AppColors.success).withValues(
          alpha: 0.09,
        ),
        borderRadius: BorderRadius.circular(AppSpacing.inputRadius),
        border: Border.all(
          color: (isError ? AppColors.danger : AppColors.success).withValues(
            alpha: 0.35,
          ),
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            isError ? Icons.error_outline_rounded : Icons.check_circle_outline,
            color: isError ? AppColors.danger : AppColors.success,
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(
              _feedback!,
              style: TextStyle(
                color: AppColors.textDark,
                height: 1.4,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final largeText = MediaQuery.textScalerOf(context).scale(1) >= 1.5;
    return Scaffold(
      appBar: AppBar(
        title: Text(largeText ? 'Health Update' : "Today's Health Update"),
      ),
      body: ResponsiveContent(
        maxWidth: AppSpacing.formMaxWidth,
        padding: const EdgeInsets.all(AppSpacing.md),
        fillHeight: true,
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : SingleChildScrollView(
                keyboardDismissBehavior:
                    ScrollViewKeyboardDismissBehavior.onDrag,
                child: Form(
                  key: _formKey,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      AppCard(
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const CircleAvatar(
                              backgroundColor: AppColors.mint,
                              child: Icon(
                                Icons.today_rounded,
                                color: AppColors.primary,
                              ),
                            ),
                            const SizedBox(width: AppSpacing.sm),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    _patientName,
                                    style: Theme.of(context)
                                        .textTheme
                                        .titleMedium
                                        ?.copyWith(
                                          color: AppColors.textDark,
                                          fontWeight: FontWeight.w900,
                                        ),
                                  ),
                                  const SizedBox(height: 4),
                                  Text(
                                    _observation == null
                                        ? 'No health update has been recorded today.'
                                        : 'Editing today\'s saved health update.',
                                    key: const Key(
                                      'daily-observation-state-message',
                                    ),
                                    style: const TextStyle(
                                      color: AppColors.textSoft,
                                      height: 1.4,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                      if (_feedback != null) ...[
                        const SizedBox(height: AppSpacing.md),
                        _feedbackBanner(),
                      ],
                      if (_patientId != null) ...[
                        const SizedBox(height: AppSpacing.lg),
                        AppCard(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const SectionHeader(
                                title: '1. Vital Measurements',
                                subtitle:
                                    'All measurements are optional. Record only what was observed.',
                              ),
                              const SizedBox(height: AppSpacing.md),
                              AdaptiveFormRow(
                                children: [
                                  _measurementField(
                                    key: const Key('systolic-input'),
                                    controller: _systolic,
                                    label: 'Systolic blood pressure',
                                    suffix: 'mmHg',
                                    validator: (value) =>
                                        _optionalNumberValidator(
                                          value,
                                          label: 'Systolic BP',
                                          minimum: 60,
                                          maximum: 260,
                                        ),
                                  ),
                                  _measurementField(
                                    key: const Key('diastolic-input'),
                                    controller: _diastolic,
                                    label: 'Diastolic blood pressure',
                                    suffix: 'mmHg',
                                    validator: (value) =>
                                        _optionalNumberValidator(
                                          value,
                                          label: 'Diastolic BP',
                                          minimum: 30,
                                          maximum: 160,
                                        ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: AppSpacing.sm),
                              AdaptiveFormRow(
                                children: [
                                  _measurementField(
                                    key: const Key('spo2-input'),
                                    controller: _spo2,
                                    label: 'SpO₂',
                                    suffix: '%',
                                    validator: (value) =>
                                        _optionalNumberValidator(
                                          value,
                                          label: 'SpO₂',
                                          minimum: 0,
                                          maximum: 100,
                                        ),
                                  ),
                                  _measurementField(
                                    key: const Key('pulse-input'),
                                    controller: _pulse,
                                    label: 'Pulse',
                                    suffix: 'bpm',
                                    validator: (value) =>
                                        _optionalNumberValidator(
                                          value,
                                          label: 'Pulse',
                                          minimum: 30,
                                          maximum: 220,
                                        ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: AppSpacing.sm),
                              _measurementField(
                                key: const Key('weight-input'),
                                controller: _weight,
                                label: 'Weight',
                                suffix: 'kg',
                                validator: (value) => _optionalNumberValidator(
                                  value,
                                  label: 'Weight',
                                  minimum: 0.01,
                                  maximum: 500,
                                ),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(height: AppSpacing.md),
                        AppCard(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const SectionHeader(
                                title: '2. Glucose / Temperature',
                                subtitle:
                                    'Select every unit explicitly; units are never inferred.',
                              ),
                              const SizedBox(height: AppSpacing.md),
                              AdaptiveFormRow(
                                children: [
                                  TextFormField(
                                    key: const Key('glucose-input'),
                                    controller: _glucose,
                                    keyboardType:
                                        const TextInputType.numberWithOptions(
                                          decimal: true,
                                        ),
                                    inputFormatters: [
                                      FilteringTextInputFormatter.allow(
                                        RegExp(r'[0-9.]'),
                                      ),
                                    ],
                                    decoration: const InputDecoration(
                                      labelText: 'Glucose value',
                                    ),
                                    validator: _glucoseValidator,
                                  ),
                                  DropdownButtonFormField<String>(
                                    key: const Key('glucose-unit-input'),
                                    initialValue: _glucoseUnit,
                                    isExpanded: true,
                                    decoration: const InputDecoration(
                                      labelText: 'Glucose unit',
                                    ),
                                    items: const [
                                      DropdownMenuItem(
                                        value: 'mg/dL',
                                        child: Text('mg/dL'),
                                      ),
                                      DropdownMenuItem(
                                        value: 'mmol/L',
                                        child: Text('mmol/L'),
                                      ),
                                    ],
                                    onChanged: _saving
                                        ? null
                                        : (value) => setState(
                                            () => _glucoseUnit = value,
                                          ),
                                    validator: (_) =>
                                        _glucose.text.trim().isNotEmpty &&
                                            _glucoseUnit == null
                                        ? 'Select a unit.'
                                        : null,
                                  ),
                                ],
                              ),
                              const SizedBox(height: AppSpacing.sm),
                              AdaptiveFormRow(
                                children: [
                                  TextFormField(
                                    key: const Key('temperature-input'),
                                    controller: _temperature,
                                    keyboardType:
                                        const TextInputType.numberWithOptions(
                                          decimal: true,
                                        ),
                                    inputFormatters: [
                                      FilteringTextInputFormatter.allow(
                                        RegExp(r'[0-9.]'),
                                      ),
                                    ],
                                    decoration: const InputDecoration(
                                      labelText: 'Temperature value',
                                    ),
                                    validator: _temperatureValidator,
                                  ),
                                  DropdownButtonFormField<String>(
                                    key: const Key('temperature-unit-input'),
                                    initialValue: _temperatureUnit,
                                    isExpanded: true,
                                    decoration: const InputDecoration(
                                      labelText: 'Temperature unit',
                                    ),
                                    items: const [
                                      DropdownMenuItem(
                                        value: 'C',
                                        child: Text('C'),
                                      ),
                                      DropdownMenuItem(
                                        value: 'F',
                                        child: Text('F'),
                                      ),
                                    ],
                                    onChanged: _saving
                                        ? null
                                        : (value) => setState(
                                            () => _temperatureUnit = value,
                                          ),
                                    validator: (_) =>
                                        _temperature.text.trim().isNotEmpty &&
                                            _temperatureUnit == null
                                        ? 'Select a unit.'
                                        : null,
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(height: AppSpacing.md),
                        AppCard(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const SectionHeader(
                                title: '3. Symptoms',
                                subtitle:
                                    'Optional observations only; no diagnosis is generated.',
                              ),
                              const SizedBox(height: AppSpacing.md),
                              TextFormField(
                                key: const Key('symptoms-input'),
                                controller: _symptoms,
                                minLines: 3,
                                maxLines: 6,
                                maxLength: 2000,
                                decoration: const InputDecoration(
                                  labelText: 'Observed symptoms',
                                  alignLabelWithHint: true,
                                ),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(height: AppSpacing.md),
                        AppCard(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const SectionHeader(
                                title: '4. Notes',
                                subtitle:
                                    'Optional caregiver notes for today’s observation.',
                              ),
                              const SizedBox(height: AppSpacing.md),
                              TextFormField(
                                key: const Key('notes-input'),
                                controller: _notes,
                                minLines: 3,
                                maxLines: 7,
                                maxLength: 4000,
                                decoration: const InputDecoration(
                                  labelText: 'Caregiver notes',
                                  alignLabelWithHint: true,
                                ),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(height: AppSpacing.lg),
                        PrimaryButton(
                          text: _saving
                              ? 'Saving…'
                              : _observation == null
                              ? 'Save Health Update'
                              : 'Update Health Update',
                          icon: Icons.save_rounded,
                          onPressed: _saving ? null : _save,
                        ),
                        const SizedBox(height: AppSpacing.md),
                      ],
                    ],
                  ),
                ),
              ),
      ),
    );
  }
}
