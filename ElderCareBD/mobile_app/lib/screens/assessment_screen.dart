import 'package:flutter/material.dart';

import '../models/model_prediction.dart';
import '../services/api_service.dart';
import '../services/model_screening_service.dart';
import '../services/prediction_service.dart';
import '../services/session_service.dart';
import '../services/text_structuring_service.dart';
import '../utils/app_colors.dart';
import '../utils/app_spacing.dart';
import '../utils/app_strings.dart';
import '../utils/input_validation.dart';
import '../utils/submission_guard.dart';
import '../widgets/accessible_checkbox_tile.dart';
import '../widgets/app_card.dart';
import '../widgets/primary_button.dart';
import '../widgets/responsive_content.dart';
import '../widgets/section_header.dart';
import 'risk_result_screen.dart';

class AssessmentScreen extends StatefulWidget {
  const AssessmentScreen({super.key});

  @override
  State<AssessmentScreen> createState() => _AssessmentScreenState();
}

class _AssessmentScreenState extends State<AssessmentScreen> {
  final ageController = TextEditingController();
  final glucoseController = TextEditingController();
  final randomGlucoseController = TextEditingController();
  final systolicBpController = TextEditingController();
  final diastolicBpController = TextEditingController();

  final heightFeetController = TextEditingController();
  final heightInchesController = TextEditingController();
  final weightController = TextEditingController();

  final noteController = TextEditingController();

  bool chestPain = false;
  bool dizziness = false;
  bool shortnessOfBreath = false;
  bool excessiveThirst = false;
  bool fatigue = false;
  bool blurredVision = false;

  PredictionContracts? _predictionContracts;
  String? _predictionContractsMessage;
  bool _loadingPredictionContracts = true;
  bool _loadingPatientProfile = true;
  String? _patientProfileMessage;
  String? _patientGender;
  bool _hasKnownDiabetes = false;
  bool _randomGlucoseContextConfirmed = false;
  bool _restingSystolicConfirmed = false;
  String? _clinicalSex;
  String? _chestPainType;

  final _submissionGuard = SubmissionGuard();

  double? calculatedBmi;
  bool get isSaving => _submissionGuard.isInProgress;

  @override
  void initState() {
    super.initState();

    heightFeetController.addListener(_calculateBmi);
    heightInchesController.addListener(_calculateBmi);
    weightController.addListener(_calculateBmi);
    _loadPredictionContracts();
    _loadPatientProfile();
  }

  @override
  void dispose() {
    ageController.dispose();
    glucoseController.dispose();
    randomGlucoseController.dispose();
    systolicBpController.dispose();
    diastolicBpController.dispose();

    heightFeetController.dispose();
    heightInchesController.dispose();
    weightController.dispose();

    noteController.dispose();

    super.dispose();
  }

  Future<void> _loadPredictionContracts() async {
    if (mounted) {
      setState(() {
        _loadingPredictionContracts = true;
        _predictionContractsMessage = null;
      });
    }

    try {
      final contracts = await ApiService.getPredictionContracts();
      if (!mounted) return;
      setState(() {
        _predictionContracts = contracts;
        _loadingPredictionContracts = false;
        _clinicalSex = null;
        _chestPainType = null;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _predictionContracts = null;
        _predictionContractsMessage = error.message;
        _loadingPredictionContracts = false;
        _clinicalSex = null;
        _chestPainType = null;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _predictionContracts = null;
        _predictionContractsMessage =
            'Research-model inputs are temporarily unavailable.';
        _loadingPredictionContracts = false;
        _clinicalSex = null;
        _chestPainType = null;
      });
    }
  }

  Future<void> _loadPatientProfile() async {
    if (mounted) {
      setState(() {
        _loadingPatientProfile = true;
        _patientProfileMessage = null;
      });
    }

    try {
      final patientId = await SessionService.getSelectedPatientId();
      if (patientId == null) {
        if (!mounted) return;
        setState(() {
          _loadingPatientProfile = false;
          _patientGender = null;
          _hasKnownDiabetes = false;
          _patientProfileMessage =
              'Select a patient to check diabetes-screening eligibility.';
        });
        return;
      }

      final patient = await ApiService.getPatientById(patientId: patientId);
      if (!mounted) return;
      final rawGender = patient?['gender']?.toString().trim();
      setState(() {
        _loadingPatientProfile = false;
        _patientGender = rawGender == null || rawGender.isEmpty
            ? null
            : rawGender;
        _hasKnownDiabetes = patient?['has_diabetes'] == true;
        _patientProfileMessage = patient == null
            ? 'The selected patient profile could not be loaded.'
            : null;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loadingPatientProfile = false;
        _patientGender = null;
        _hasKnownDiabetes = false;
        _patientProfileMessage =
            'The selected patient profile could not be loaded.';
      });
    }
  }

  void _calculateBmi() {
    final heightCm = InputValidation.tryConvertFeetAndInchesToCm(
      heightFeetController.text,
      heightInchesController.text,
    );
    setState(() {
      calculatedBmi = InputValidation.tryCalculateBmi(
        heightCm?.toString() ?? '',
        weightController.text,
      );
    });
  }

  void _analyzeNote() {
    final rawExtraction = TextStructuringService.extract(noteController.text);
    final validation = InputValidation.validateExtraction(rawExtraction);
    final validSuggestions = validation.suggestions;
    final applied = validSuggestions.applyPreservingManualValues(
      glucoseText: glucoseController.text,
      systolicBpText: systolicBpController.text,
      diastolicBpText: diastolicBpController.text,
      chestPain: chestPain,
      dizziness: dizziness,
      shortnessOfBreath: shortnessOfBreath,
      excessiveThirst: excessiveThirst,
      fatigue: fatigue,
      blurredVision: blurredVision,
      glucoseTextUsesMmolL: true,
    );

    setState(() {
      glucoseController.text = applied.glucoseText;
      systolicBpController.text = applied.systolicBpText;
      diastolicBpController.text = applied.diastolicBpText;
      chestPain = applied.chestPain;
      dizziness = applied.dizziness;
      shortnessOfBreath = applied.shortnessOfBreath;
      excessiveThirst = applied.excessiveThirst;
      fatigue = applied.fatigue;
      blurredVision = applied.blurredVision;
    });

    if (validation.rejectedMessages.isNotEmpty ||
        applied.conflicts.isNotEmpty) {
      final messages = <String>[...validation.rejectedMessages];
      if (validSuggestions.hasSuggestions) {
        messages.add('Other valid suggestions were applied.');
      }
      if (applied.conflicts.isNotEmpty) {
        messages.add(
          'Manual values kept: ${applied.conflicts.map((conflict) => conflict.description).join('; ')}.',
        );
      }
      _showMessage(messages.join(' '));
    } else if (validSuggestions.hasSuggestions) {
      _showMessage(
        'Extracted suggestions applied. Please review them before saving.',
      );
    } else {
      _showMessage('No supported health values or symptoms found in the note.');
    }
  }

  Future<void> _saveAssessment() async {
    final heightCm = InputValidation.tryConvertFeetAndInchesToCm(
      heightFeetController.text,
      heightInchesController.text,
    );
    if (heightCm == null) {
      _showMessage(
        'Please enter height as whole feet from 1 to 9 and inches from 0 to 11.',
      );
      return;
    }

    final validation = InputValidation.validateAssessment(
      ageText: ageController.text,
      glucoseText: glucoseController.text,
      systolicBpText: systolicBpController.text,
      diastolicBpText: diastolicBpController.text,
      heightText: heightCm.toString(),
      weightText: weightController.text,
    );
    if (!validation.isValid) {
      _showMessage(validation.message!);
      return;
    }

    if (!_submissionGuard.tryStart()) return;
    setState(() {});

    try {
      final values = validation.values!;
      final note = noteController.text;
      final patientId = await SessionService.getSelectedPatientId();

      if (patientId == null) {
        _showMessage('Please save or select a patient profile first.');
        return;
      }

      final prediction = PredictionService.predict(
        RiskPredictionInput(
          age: values.age,
          glucose: values.glucose,
          systolicBp: values.systolicBp,
          diastolicBp: values.diastolicBp,
          bmi: values.bmi,
          chestPain: chestPain,
          dizziness: dizziness,
          shortnessOfBreath: shortnessOfBreath,
          excessiveThirst: excessiveThirst,
          fatigue: fatigue,
          blurredVision: blurredVision,
        ),
      );

      final diabetesInputDecision = ModelScreeningService.buildDiabetesInput(
        contracts: _predictionContracts,
        hasKnownDiabetes: _hasKnownDiabetes,
        patientGender: _patientGender,
        randomGlucoseContextConfirmed: _randomGlucoseContextConfirmed,
        randomGlucoseText: randomGlucoseController.text,
        age: values.age,
        systolicBp: values.systolicBp,
        diastolicBp: values.diastolicBp,
        bmi: values.bmi,
      );
      final heartInputDecision = ModelScreeningService.buildHeartInput(
        contracts: _predictionContracts,
        clinicalSex: _clinicalSex,
        chestPainType: _chestPainType,
        restingSystolicConfirmed: _restingSystolicConfirmed,
        age: values.age,
        systolicBp: values.systolicBp,
      );

      final modelPredictions = await Future.wait([
        _predictDiabetesSafely(patientId, diabetesInputDecision),
        _predictHeartSafely(patientId, heartInputDecision),
      ]);
      final diabetesModelPrediction = modelPredictions[0];
      final heartModelPrediction = modelPredictions[1];

      final result = await ApiService.createAssessment(
        patientId: patientId,
        age: values.age,
        glucose: values.glucose,
        systolicBp: values.systolicBp,
        diastolicBp: values.diastolicBp,
        bmi: values.bmi,
        heightCm: values.heightCm,
        weightKg: values.weightKg,
        note: note,
        chestPain: chestPain,
        dizziness: dizziness,
        shortnessOfBreath: shortnessOfBreath,
        excessiveThirst: excessiveThirst,
        fatigue: fatigue,
        blurredVision: blurredVision,
        diabetesRisk: prediction.diabetesRisk,
        heartRisk: prediction.heartRisk,
        overallRisk: prediction.overallRisk,
        recommendation: prediction.recommendation,
        diabetesModelInput: diabetesInputDecision.input,
        heartModelInput: heartInputDecision.input,
      );

      if (!mounted) return;

      final statusCode = result['statusCode'];
      final isSuccessful =
          statusCode is int && statusCode >= 200 && statusCode < 300;

      if (isSuccessful) {
        final body = result['body'];
        final canonicalPredictions = AssessmentPredictions.fromCreateResponse(
          body,
          diabetesFallback: diabetesModelPrediction,
          heartFallback: heartModelPrediction,
        );
        Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => RiskResultScreen(
              diabetesRisk: prediction.diabetesRisk,
              heartRisk: prediction.heartRisk,
              overallRisk: prediction.overallRisk,
              recommendation: prediction.recommendation,
              predictions: canonicalPredictions,
            ),
          ),
        );
      } else {
        _showMessage(
          ApiService.errorMessage(
            result,
            fallback:
                'Could not save assessment. Please check the entered values.',
          ),
        );
      }
    } catch (error) {
      debugPrint('ASSESSMENT SAVE ERROR: $error');
      if (!mounted) return;
      _showMessage(
        error is ApiException
            ? error.message
            : 'Could not save assessment. Please try again.',
      );
    } finally {
      _submissionGuard.finish();
      if (mounted) setState(() {});
    }
  }

  Future<DiseasePrediction> _predictDiabetesSafely(
    int patientId,
    ModelInputDecision<DiabetesModelInput> decision,
  ) async {
    final input = decision.input;
    if (input == null) {
      return DiseasePrediction.fallback(
        disease: 'diabetes',
        predictionStatus: decision.predictionStatus,
        message: decision.message,
        predictionSource:
            decision.predictionStatus == 'not_applicable_known_diabetes'
            ? 'known_condition'
            : 'heuristic_demo_v1',
      );
    }

    try {
      return await ApiService.predictDiabetes(
        patientId: patientId,
        input: input,
      );
    } catch (_) {
      return DiseasePrediction.fallback(
        disease: 'diabetes',
        predictionStatus: 'inference_failed',
        message:
            'The diabetes research model could not complete screening. The assessment was saved with the heuristic demo fallback.',
      );
    }
  }

  Future<DiseasePrediction> _predictHeartSafely(
    int patientId,
    ModelInputDecision<HeartModelInput> decision,
  ) async {
    final input = decision.input;
    if (input == null) {
      return DiseasePrediction.fallback(
        disease: 'heart',
        predictionStatus: decision.predictionStatus,
        message: decision.message,
      );
    }

    try {
      return await ApiService.predictHeart(patientId: patientId, input: input);
    } catch (_) {
      return DiseasePrediction.fallback(
        disease: 'heart',
        predictionStatus: 'inference_failed',
        message:
            'The heart research model could not complete screening. The assessment was saved with the heuristic demo fallback.',
      );
    }
  }

  void _showMessage(String message) {
    if (!mounted) return;

    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  Color _bmiColor() {
    if (calculatedBmi == null) return AppColors.primary;

    if (calculatedBmi! >= 30) return AppColors.danger;
    if (calculatedBmi! >= 25) return AppColors.warning;
    if (calculatedBmi! < 18.5) return AppColors.info;

    return AppColors.success;
  }

  String _bmiStatus() {
    if (calculatedBmi == null) return 'Enter height and weight';

    if (calculatedBmi! < 18.5) return 'Underweight';
    if (calculatedBmi! < 25) return 'Normal';
    if (calculatedBmi! < 30) return 'Overweight';

    return 'Obese';
  }

  List<ModelCategoryOption> _heartCategoryOptions(String featureName) {
    final contract = _predictionContracts?.heart;
    if (contract == null || !contract.available) return const [];
    return contract.featureNamed(featureName)?.categoryOptions ?? const [];
  }

  String _supportedRange(ModelFeatureContract? feature) {
    if (feature?.minimum == null || feature?.maximum == null) {
      return 'The trusted model range is supplied by the backend.';
    }

    String format(double value) => value == value.roundToDouble()
        ? value.toInt().toString()
        : value.toString();
    final unit = feature!.unit?.trim();
    return 'Trusted model range: ${format(feature.minimum!)} to ${format(feature.maximum!)}${unit == null || unit.isEmpty ? '' : ' $unit'}.';
  }

  String _categoryDisplayLabel(String label) {
    if (label.isEmpty) return label;
    return '${label[0].toUpperCase()}${label.substring(1)}';
  }

  @override
  Widget build(BuildContext context) {
    final strings = AppStrings.of(context);
    final bmiColor = _bmiColor();
    final heartSexOptions = _heartCategoryOptions('sex');
    final heartChestPainOptions = _heartCategoryOptions('cp');

    return Scaffold(
      appBar: AppBar(title: Text(strings.assessment)),
      body: ResponsiveContent(
        maxWidth: 900,
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
        child: SingleChildScrollView(
          keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _IntroCard(),
              const SizedBox(height: 22),

              const SectionHeader(
                key: Key('assessment-section-basic'),
                title: '1. Basic measurements',
                subtitle: 'Record current measurements using the shown units.',
              ),
              const SizedBox(height: 12),

              TextField(
                controller: ageController,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Age',
                  hintText: 'Example: 67',
                  prefixIcon: Icon(Icons.person_rounded),
                ),
              ),
              const SizedBox(height: 14),

              TextField(
                controller: glucoseController,
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
                decoration: const InputDecoration(
                  labelText: ModelScreeningService.generalGlucoseLabel,
                  hintText: 'Example: 6.1 or 7.00',
                  helperText:
                      'Enter a decimal mmol/L reading. This general value is not used as the confirmed DiaBD measurement.',
                  helperMaxLines: 3,
                  prefixIcon: Icon(Icons.bloodtype_rounded),
                ),
              ),
              const SizedBox(height: 14),

              AdaptiveFormRow(
                children: [
                  TextField(
                    controller: systolicBpController,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'Systolic BP',
                      hintText: '145',
                    ),
                  ),
                  TextField(
                    controller: diastolicBpController,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'Diastolic BP',
                      hintText: '90',
                    ),
                  ),
                ],
              ),

              const SizedBox(height: 22),

              const SectionHeader(
                title: 'Body measurements',
                subtitle: 'BMI is calculated from height and weight.',
              ),
              const SizedBox(height: 12),

              AdaptiveFormRow(
                children: [
                  TextField(
                    controller: heightFeetController,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'Height (feet)',
                      hintText: '5',
                      prefixIcon: Icon(Icons.height_rounded),
                    ),
                  ),
                  TextField(
                    controller: heightInchesController,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'Height (inches)',
                      hintText: '3',
                    ),
                  ),
                ],
              ),

              const SizedBox(height: 14),

              TextField(
                controller: weightController,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Weight (kg)',
                  hintText: '65',
                  helperText:
                      'Height is converted to centimetres before BMI calculation and saving.',
                  helperMaxLines: 2,
                  prefixIcon: Icon(Icons.monitor_weight_rounded),
                ),
              ),

              const SizedBox(height: 14),

              AppCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        CircleAvatar(
                          backgroundColor: bmiColor.withValues(alpha: 0.12),
                          child: Icon(Icons.calculate_rounded, color: bmiColor),
                        ),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Calculated BMI',
                                style: TextStyle(
                                  color: AppColors.textSoft,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                calculatedBmi == null
                                    ? 'Not calculated'
                                    : calculatedBmi!.toStringAsFixed(1),
                                style: TextStyle(
                                  fontSize: 24,
                                  fontWeight: FontWeight.w900,
                                  color: bmiColor,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 8,
                      ),
                      decoration: BoxDecoration(
                        color: bmiColor.withValues(alpha: 0.10),
                        borderRadius: BorderRadius.circular(99),
                      ),
                      child: Text(
                        _bmiStatus(),
                        style: TextStyle(
                          color: bmiColor,
                          fontSize: 12,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 22),

              const SectionHeader(
                key: Key('assessment-section-models'),
                title: '2–3. Optional disease screening',
                subtitle:
                    'DiaBD v3 diabetes and Heart v2 screening run only with compatible confirmed inputs.',
              ),
              const SizedBox(height: 12),

              AppCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'These non-diagnostic models run only when the exact measurement context and every supported input are provided. Missing model inputs do not prevent saving the general assessment.',
                      style: TextStyle(
                        color: AppColors.textSoft,
                        height: 1.5,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    if (_loadingPredictionContracts) ...[
                      const SizedBox(height: 14),
                      const LinearProgressIndicator(),
                      const SizedBox(height: 8),
                      Text(
                        'Checking trusted model availability...',
                        style: TextStyle(color: AppColors.textSoft),
                      ),
                    ] else if (_predictionContractsMessage != null) ...[
                      const SizedBox(height: 12),
                      Text(
                        _predictionContractsMessage!,
                        style: TextStyle(
                          color: AppColors.textSoft,
                          height: 1.4,
                        ),
                      ),
                      TextButton.icon(
                        onPressed: _loadPredictionContracts,
                        icon: const Icon(Icons.refresh_rounded),
                        label: const Text('Retry model availability'),
                      ),
                    ],
                    const SizedBox(height: 18),
                    Text(
                      strings.diabetesScreening,
                      style: TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w900,
                        color: AppColors.textDark,
                      ),
                    ),
                    if (!_loadingPredictionContracts &&
                        _predictionContracts?.diabetes?.available == false)
                      Text(
                        _predictionContracts?.diabetes?.unavailableReason ??
                            'The diabetes research model is currently unavailable.',
                        style: TextStyle(
                          color: AppColors.warning,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    const SizedBox(height: 6),
                    Text(
                      'Bangladesh-specific research/demo screening of contemporaneous recorded diabetes status. It does not diagnose diabetes or predict future risk.',
                      style: TextStyle(color: AppColors.textSoft, height: 1.45),
                    ),
                    if (_loadingPatientProfile) ...[
                      const SizedBox(height: 12),
                      const LinearProgressIndicator(),
                      const SizedBox(height: 8),
                      Text(
                        'Checking the selected patient profile...',
                        style: TextStyle(color: AppColors.textSoft),
                      ),
                    ] else if (_patientProfileMessage != null) ...[
                      const SizedBox(height: 10),
                      Text(
                        _patientProfileMessage!,
                        style: TextStyle(color: AppColors.warning),
                      ),
                      TextButton.icon(
                        onPressed: _loadPatientProfile,
                        icon: const Icon(Icons.refresh_rounded),
                        label: const Text('Retry patient profile'),
                      ),
                    ] else if (_hasKnownDiabetes) ...[
                      const SizedBox(height: 10),
                      Text(
                        'Diabetes is already recorded for this patient, so DiaBD screening is not applicable and no model result will be created.',
                        key: const Key('known-diabetes-bypass-message'),
                        style: TextStyle(
                          color: AppColors.primary,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ] else if (_patientGender != 'Female' &&
                        _patientGender != 'Male') ...[
                      const SizedBox(height: 10),
                      Text(
                        'The recorded gender is ${_patientGender ?? 'unknown'}. DiaBD supports only Female or Male, so no gender will be fabricated and the model will not run.',
                        key: const Key('unsupported-diabetes-gender-message'),
                        style: TextStyle(
                          color: AppColors.warning,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ] else ...[
                      const SizedBox(height: 10),
                      Text(
                        'Using recorded gender: $_patientGender. Age, current systolic/diastolic BP, and calculated BMI are reused from this assessment.',
                        key: const Key('diabd-reused-inputs-message'),
                        style: TextStyle(
                          color: AppColors.textSoft,
                          height: 1.45,
                        ),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        key: const Key('random-glucose-mmol-l-input'),
                        controller: randomGlucoseController,
                        keyboardType: const TextInputType.numberWithOptions(
                          decimal: true,
                        ),
                        decoration: InputDecoration(
                          labelText: ModelScreeningService.randomGlucoseLabel,
                          hintText: 'Example: 6.1 or 7.00',
                          helperText:
                              '${_supportedRange(_predictionContracts?.diabetes?.featureNamed('glucose'))} Do not enter mg/dL, fasting, post-meal, or OGTT values.',
                          helperMaxLines: 3,
                          prefixIcon: const Icon(Icons.water_drop_rounded),
                        ),
                      ),
                      AccessibleCheckboxTile(
                        key: const Key('confirm-random-glucose-mmol-l'),
                        value: _randomGlucoseContextConfirmed,
                        onChanged: (value) {
                          setState(() {
                            _randomGlucoseContextConfirmed = value ?? false;
                          });
                        },
                        title: ModelScreeningService
                            .randomGlucoseConfirmationLabel,
                        subtitle:
                            'Left unconfirmed, DiaBD will not run; the general assessment can still be saved.',
                      ),
                    ],
                    const Divider(height: 32),
                    Text(
                      strings.heartScreening,
                      style: TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w900,
                        color: AppColors.textDark,
                      ),
                    ),
                    if (!_loadingPredictionContracts &&
                        _predictionContracts?.heart?.available == false)
                      Text(
                        _predictionContracts?.heart?.unavailableReason ??
                            'The heart research model is currently unavailable.',
                        style: TextStyle(
                          color: AppColors.warning,
                          fontWeight: FontWeight.w700,
                        ),
                      )
                    else if (_predictionContracts?.heart?.available == true &&
                        (heartSexOptions.isEmpty ||
                            heartChestPainOptions.isEmpty))
                      Text(
                        'Trusted category labels are unavailable, so the heart research model will not run.',
                        style: TextStyle(
                          color: AppColors.warning,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    const SizedBox(height: 6),
                    Text(
                      'Clinical sex and chest-pain type use the trusted model metadata. They are never inferred from the patient profile or the symptom checkbox.',
                      style: TextStyle(color: AppColors.textSoft, height: 1.45),
                    ),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<String>(
                      key: ValueKey(
                        'heart-clinical-sex-input-${heartSexOptions.map((option) => option.label).join('|')}',
                      ),
                      initialValue: _clinicalSex,
                      isExpanded: true,
                      decoration: const InputDecoration(
                        labelText: 'Clinical sex for this model',
                        helperText:
                            'Select only when the supported value is known.',
                        helperMaxLines: 2,
                      ),
                      hint: const Text('Not provided'),
                      items: heartSexOptions
                          .map(
                            (option) => DropdownMenuItem<String>(
                              value: option.label,
                              child: Text(_categoryDisplayLabel(option.label)),
                            ),
                          )
                          .toList(growable: false),
                      onChanged: heartSexOptions.isEmpty
                          ? null
                          : (value) => setState(() => _clinicalSex = value),
                    ),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<String>(
                      key: ValueKey(
                        'heart-chest-pain-type-input-${heartChestPainOptions.map((option) => option.label).join('|')}',
                      ),
                      initialValue: _chestPainType,
                      isExpanded: true,
                      decoration: const InputDecoration(
                        labelText:
                            ModelScreeningService.heartChestPainTypeLabel,
                        helperText:
                            'This four-category value is not the yes/no symptom above.',
                        helperMaxLines: 2,
                      ),
                      hint: const Text('Not provided'),
                      items: heartChestPainOptions
                          .map(
                            (option) => DropdownMenuItem<String>(
                              value: option.label,
                              child: Text(_categoryDisplayLabel(option.label)),
                            ),
                          )
                          .toList(growable: false),
                      onChanged: heartChestPainOptions.isEmpty
                          ? null
                          : (value) => setState(() => _chestPainType = value),
                    ),
                    const SizedBox(height: 8),
                    AccessibleCheckboxTile(
                      key: const Key('confirm-resting-systolic'),
                      value: _restingSystolicConfirmed,
                      onChanged: (value) {
                        setState(() {
                          _restingSystolicConfirmed = value ?? false;
                        });
                      },
                      title: 'The systolic BP above was measured at rest',
                      subtitle:
                          '${_supportedRange(_predictionContracts?.heart?.featureNamed('trestbps'))} Left unconfirmed, the heart model will not run.',
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 22),

              const SectionHeader(
                key: Key('assessment-section-symptoms'),
                title: '4. Symptoms',
                subtitle: 'Select only symptoms reported for this assessment.',
              ),
              const SizedBox(height: 12),

              _SymptomTile(
                title: 'Chest pain',
                value: chestPain,
                onChanged: (value) {
                  setState(() {
                    chestPain = value ?? false;
                  });
                },
              ),
              _SymptomTile(
                title: 'Dizziness',
                value: dizziness,
                onChanged: (value) {
                  setState(() {
                    dizziness = value ?? false;
                  });
                },
              ),
              _SymptomTile(
                title: 'Shortness of breath',
                value: shortnessOfBreath,
                onChanged: (value) {
                  setState(() {
                    shortnessOfBreath = value ?? false;
                  });
                },
              ),
              _SymptomTile(
                title: 'Excessive thirst',
                value: excessiveThirst,
                onChanged: (value) {
                  setState(() {
                    excessiveThirst = value ?? false;
                  });
                },
              ),
              _SymptomTile(
                title: 'Fatigue',
                value: fatigue,
                onChanged: (value) {
                  setState(() {
                    fatigue = value ?? false;
                  });
                },
              ),
              _SymptomTile(
                title: 'Blurred vision',
                value: blurredVision,
                onChanged: (value) {
                  setState(() {
                    blurredVision = value ?? false;
                  });
                },
              ),

              const SizedBox(height: 22),

              const SectionHeader(
                key: Key('assessment-section-notes'),
                title: '5. Caregiver notes',
                subtitle:
                    'Optional note extraction suggests values for review; it does not diagnose.',
              ),
              const SizedBox(height: 12),

              TextField(
                controller: noteController,
                maxLines: 4,
                decoration: const InputDecoration(
                  labelText: 'Caregiver note',
                  hintText:
                      'Example: Patient has high sugar, weakness, and dizziness.',
                  prefixIcon: Icon(Icons.notes_rounded),
                ),
              ),

              const SizedBox(height: 12),

              OutlinedButton.icon(
                onPressed: _analyzeNote,
                icon: const Icon(Icons.auto_fix_high_rounded),
                label: const Text('Extract Suggestions from Note'),
              ),

              const SizedBox(height: 24),

              const SectionHeader(
                key: Key('assessment-section-submit'),
                title: '6. Review and submit',
                subtitle:
                    'Confirm the entered measurements before saving this assessment.',
              ),
              const SizedBox(height: 12),

              if (isSaving)
                Center(
                  child: Semantics(
                    label: 'Saving assessment',
                    liveRegion: true,
                    child: CircularProgressIndicator(),
                  ),
                )
              else
                PrimaryButton(
                  text: 'Generate Risk Assessment',
                  icon: Icons.health_and_safety_rounded,
                  onPressed: _saveAssessment,
                ),

              const SizedBox(height: 14),

              Text(
                'Note: This feature provides preliminary screening support only and is not a replacement for professional medical diagnosis.',
                style: TextStyle(
                  color: AppColors.textSoft,
                  height: 1.5,
                  fontSize: 12.5,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _IntroCard extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const CircleAvatar(
            backgroundColor: AppColors.mint,
            child: Icon(Icons.monitor_heart_rounded, color: AppColors.primary),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Text(
              'Enter elderly patient vitals, symptoms, height, and weight. BMI will be calculated automatically before generating the health risk assessment.',
              style: TextStyle(
                color: AppColors.textDark,
                height: 1.55,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _SymptomTile extends StatelessWidget {
  final String title;
  final bool value;
  final ValueChanged<bool?> onChanged;

  const _SymptomTile({
    required this.title,
    required this.value,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: AppCard(
        padding: const EdgeInsets.all(AppSpacing.xs),
        child: AccessibleCheckboxTile(
          title: title,
          value: value,
          onChanged: onChanged,
        ),
      ),
    );
  }
}
