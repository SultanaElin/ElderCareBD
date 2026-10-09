import 'package:flutter/material.dart';

import '../services/api_service.dart';
import '../services/session_service.dart';
import '../utils/app_colors.dart';
import '../utils/app_spacing.dart';
import '../utils/app_strings.dart';
import '../utils/input_validation.dart';
import '../utils/submission_guard.dart';
import '../widgets/accessible_checkbox_tile.dart';
import '../widgets/app_card.dart';
import '../widgets/primary_button.dart';
import '../widgets/responsive_content.dart';

class PatientProfileScreen extends StatefulWidget {
  const PatientProfileScreen({super.key});

  @override
  State<PatientProfileScreen> createState() => _PatientProfileScreenState();
}

class _PatientProfileScreenState extends State<PatientProfileScreen> {
  final nameController = TextEditingController();
  final ageController = TextEditingController();
  final phoneController = TextEditingController();
  final addressController = TextEditingController();
  final emergencyContactController = TextEditingController();
  final diseaseHistoryController = TextEditingController();

  String gender = 'Male';

  bool hasDiabetes = false;
  bool hasHeartDisease = false;
  bool hasHypertension = false;
  bool hasKidneyDisease = false;
  bool hasStrokeHistory = false;

  final _submissionGuard = SubmissionGuard();

  bool profileSaved = false;
  bool get isSaving => _submissionGuard.isInProgress;
  int? savedPatientId;

  @override
  void dispose() {
    nameController.dispose();
    ageController.dispose();
    phoneController.dispose();
    addressController.dispose();
    emergencyContactController.dispose();
    diseaseHistoryController.dispose();
    super.dispose();
  }

  Future<void> _saveProfile() async {
    debugPrint('SAVE PATIENT BUTTON CLICKED');

    final validation = InputValidation.validatePatient(
      nameText: nameController.text,
      ageText: ageController.text,
      gender: gender,
    );
    if (!validation.isValid) {
      _showMessage(validation.message!);
      return;
    }

    if (!_submissionGuard.tryStart()) return;
    setState(() {});

    _showMessage('Saving patient profile...');

    try {
      final values = validation.values!;
      final caregiverId = await SessionService.getCaregiverId();

      debugPrint('FOUND CAREGIVER ID: $caregiverId');

      if (caregiverId == null) {
        _showMessage('Caregiver session not found. Please login again.');
        return;
      }

      final result = await ApiService.createPatient(
        caregiverId: caregiverId,
        name: values.name,
        age: values.age,
        gender: values.gender,
        phone: phoneController.text.trim(),
        address: addressController.text.trim(),
        emergencyContact: emergencyContactController.text.trim(),
        hasDiabetes: hasDiabetes,
        hasHeartDisease: hasHeartDisease,
        hasHypertension: hasHypertension,
        hasKidneyDisease: hasKidneyDisease,
        hasStrokeHistory: hasStrokeHistory,
        diseaseHistory: diseaseHistoryController.text.trim(),
      );

      debugPrint('PATIENT SAVE RESULT: $result');

      if (!mounted) return;

      final statusCode = result['statusCode'];
      final rawBody = result['body'];
      final body = rawBody is Map<String, dynamic>
          ? rawBody
          : <String, dynamic>{};
      final rawPatientId = body['patient_id'];
      final patientId = rawPatientId is num ? rawPatientId.toInt() : null;
      final isSuccessful =
          statusCode is int && statusCode >= 200 && statusCode < 300;

      if (isSuccessful && patientId != null) {
        await SessionService.saveSelectedPatient(
          patientId: patientId,
          patientName: values.name,
        );
        if (!mounted) return;

        setState(() {
          profileSaved = true;
          savedPatientId = patientId;
        });

        _showMessage('Patient saved successfully. Patient ID: $patientId');
      } else {
        _showMessage(
          ApiService.errorMessage(
            result,
            fallback: isSuccessful
                ? 'Patient response did not include a patient ID.'
                : 'Could not save patient. Please check the entered values.',
          ),
        );
      }
    } catch (error) {
      debugPrint('PATIENT SAVE ERROR: $error');

      if (!mounted) return;

      _showMessage(
        error is ApiException
            ? error.message
            : 'Could not save patient. Please try again.',
      );
    } finally {
      _submissionGuard.finish();
      if (mounted) setState(() {});
    }
  }

  void _showMessage(String message) {
    if (!mounted) return;

    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final strings = AppStrings.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(strings.addPatient)),
      body: ResponsiveContent(
        maxWidth: AppSpacing.formMaxWidth,
        child: SingleChildScrollView(
          keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _IntroCard(),
              const SizedBox(height: 20),

              Text(
                'Basic information',
                style: TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w900,
                  color: AppColors.primary,
                ),
              ),
              const SizedBox(height: 12),

              TextField(
                controller: nameController,
                decoration: const InputDecoration(
                  labelText: 'Patient full name',
                  prefixIcon: Icon(Icons.elderly_rounded),
                ),
              ),
              const SizedBox(height: 14),

              AdaptiveFormRow(
                children: [
                  TextField(
                    controller: ageController,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'Age',
                      prefixIcon: Icon(Icons.cake_rounded),
                    ),
                  ),
                  DropdownButtonFormField<String>(
                    initialValue: gender,
                    decoration: const InputDecoration(
                      labelText: 'Gender',
                      prefixIcon: Icon(Icons.wc_rounded),
                    ),
                    items: const [
                      DropdownMenuItem(value: 'Male', child: Text('Male')),
                      DropdownMenuItem(value: 'Female', child: Text('Female')),
                      DropdownMenuItem(value: 'Other', child: Text('Other')),
                    ],
                    onChanged: (value) {
                      if (value == null) return;

                      setState(() {
                        gender = value;
                      });
                    },
                  ),
                ],
              ),

              const SizedBox(height: 14),

              TextField(
                controller: phoneController,
                keyboardType: TextInputType.phone,
                decoration: const InputDecoration(
                  labelText: 'Patient phone',
                  prefixIcon: Icon(Icons.phone_rounded),
                ),
              ),
              const SizedBox(height: 14),

              TextField(
                controller: addressController,
                maxLines: 2,
                decoration: const InputDecoration(
                  labelText: 'Address',
                  prefixIcon: Icon(Icons.location_on_outlined),
                  alignLabelWithHint: true,
                ),
              ),

              const SizedBox(height: 22),

              Text(
                'Medical background',
                style: TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w900,
                  color: AppColors.primary,
                ),
              ),
              const SizedBox(height: 8),

              _ConditionTile(
                title: 'Diabetes',
                value: hasDiabetes,
                onChanged: (value) {
                  setState(() {
                    hasDiabetes = value ?? false;
                  });
                },
              ),
              _ConditionTile(
                title: 'Heart disease',
                value: hasHeartDisease,
                onChanged: (value) {
                  setState(() {
                    hasHeartDisease = value ?? false;
                  });
                },
              ),
              _ConditionTile(
                title: 'Hypertension / High blood pressure',
                value: hasHypertension,
                onChanged: (value) {
                  setState(() {
                    hasHypertension = value ?? false;
                  });
                },
              ),
              _ConditionTile(
                title: 'Kidney disease',
                value: hasKidneyDisease,
                onChanged: (value) {
                  setState(() {
                    hasKidneyDisease = value ?? false;
                  });
                },
              ),
              _ConditionTile(
                title: 'Stroke history',
                value: hasStrokeHistory,
                onChanged: (value) {
                  setState(() {
                    hasStrokeHistory = value ?? false;
                  });
                },
              ),

              const SizedBox(height: 14),

              TextField(
                controller: diseaseHistoryController,
                maxLines: 4,
                decoration: const InputDecoration(
                  labelText: 'Additional disease history',
                  hintText:
                      'Example: Previous surgery, allergies, long-term weakness...',
                  alignLabelWithHint: true,
                ),
              ),

              const SizedBox(height: 22),

              Text(
                'Emergency contact',
                style: TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w900,
                  color: AppColors.primary,
                ),
              ),
              const SizedBox(height: 12),

              TextField(
                controller: emergencyContactController,
                keyboardType: TextInputType.phone,
                decoration: const InputDecoration(
                  labelText: 'Emergency contact number',
                  prefixIcon: Icon(Icons.emergency_rounded),
                ),
              ),

              const SizedBox(height: 22),

              if (profileSaved)
                _ProfilePreview(
                  patientId: savedPatientId,
                  name: nameController.text,
                  age: ageController.text,
                  gender: gender,
                  hasDiabetes: hasDiabetes,
                  hasHeartDisease: hasHeartDisease,
                  hasHypertension: hasHypertension,
                  hasKidneyDisease: hasKidneyDisease,
                  hasStrokeHistory: hasStrokeHistory,
                ),

              const SizedBox(height: 20),

              if (isSaving)
                Center(
                  child: Semantics(
                    label: 'Saving patient profile',
                    liveRegion: true,
                    child: const CircularProgressIndicator(),
                  ),
                )
              else
                PrimaryButton(
                  text: '${strings.save} Patient Profile',
                  icon: Icons.save_rounded,
                  onPressed: _saveProfile,
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
            backgroundColor: AppColors.sky,
            child: Icon(Icons.elderly_rounded, color: AppColors.primary),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Text(
              'Create an elderly patient profile so health assessments, prescriptions, and medicine reminders can be linked to the correct person.',
              style: TextStyle(
                height: 1.55,
                fontWeight: FontWeight.w600,
                color: Colors.black87,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ConditionTile extends StatelessWidget {
  final String title;
  final bool value;
  final ValueChanged<bool?> onChanged;

  const _ConditionTile({
    required this.title,
    required this.value,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return AccessibleCheckboxTile(
      title: title,
      value: value,
      onChanged: onChanged,
    );
  }
}

class _ProfilePreview extends StatelessWidget {
  final int? patientId;
  final String name;
  final String age;
  final String gender;
  final bool hasDiabetes;
  final bool hasHeartDisease;
  final bool hasHypertension;
  final bool hasKidneyDisease;
  final bool hasStrokeHistory;

  const _ProfilePreview({
    required this.patientId,
    required this.name,
    required this.age,
    required this.gender,
    required this.hasDiabetes,
    required this.hasHeartDisease,
    required this.hasHypertension,
    required this.hasKidneyDisease,
    required this.hasStrokeHistory,
  });

  @override
  Widget build(BuildContext context) {
    final conditions = <String>[];

    if (hasDiabetes) conditions.add('Diabetes');
    if (hasHeartDisease) conditions.add('Heart Disease');
    if (hasHypertension) conditions.add('Hypertension');
    if (hasKidneyDisease) conditions.add('Kidney Disease');
    if (hasStrokeHistory) conditions.add('Stroke History');

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Saved profile preview',
            style: TextStyle(
              fontWeight: FontWeight.w900,
              color: AppColors.primary,
            ),
          ),
          const SizedBox(height: 10),
          if (patientId != null)
            _PreviewRow(title: 'Patient ID', value: patientId.toString()),
          _PreviewRow(title: 'Name', value: name),
          _PreviewRow(title: 'Age', value: age),
          _PreviewRow(title: 'Gender', value: gender),
          _PreviewRow(
            title: 'Major conditions',
            value: conditions.isEmpty ? 'None selected' : conditions.join(', '),
          ),
        ],
      ),
    );
  }
}

class _PreviewRow extends StatelessWidget {
  final String title;
  final String value;

  const _PreviewRow({required this.title, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 7),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Text(title, style: TextStyle(color: Colors.black54)),
          ),
          Expanded(
            child: Text(
              value,
              textAlign: TextAlign.right,
              style: TextStyle(
                fontWeight: FontWeight.w700,
                color: Colors.black87,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
