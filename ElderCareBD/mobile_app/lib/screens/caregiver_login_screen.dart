import 'package:flutter/material.dart';

import '../models/caregiver_verification.dart';
import '../services/api_service.dart';
import '../services/session_service.dart';
import '../utils/app_colors.dart';
import '../utils/app_spacing.dart';
import '../utils/app_strings.dart';
import '../utils/input_validation.dart';
import '../utils/submission_guard.dart';
import '../widgets/language_toggle_button.dart';
import '../widgets/primary_button.dart';
import '../widgets/responsive_content.dart';
import 'caregiver_dashboard_screen.dart';
import 'caregiver_otp_verification_screen.dart';

class CaregiverLoginScreen extends StatefulWidget {
  const CaregiverLoginScreen({super.key, this.initialRegisterMode = true});

  final bool initialRegisterMode;

  @override
  State<CaregiverLoginScreen> createState() => _CaregiverLoginScreenState();
}

class _CaregiverLoginScreenState extends State<CaregiverLoginScreen> {
  final nameController = TextEditingController();
  final phoneController = TextEditingController();
  final passwordController = TextEditingController();

  final _submissionGuard = SubmissionGuard();

  late bool isRegisterMode;
  CaregiverVerificationChannel verificationChannel =
      CaregiverVerificationChannel.email;
  bool get isLoading => _submissionGuard.isInProgress;

  @override
  void initState() {
    super.initState();
    isRegisterMode = widget.initialRegisterMode;
  }

  @override
  void dispose() {
    nameController.dispose();
    phoneController.dispose();
    passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final registering = isRegisterMode;
    final name = nameController.text.trim();
    final phoneOrEmail = phoneController.text.trim();
    final password = passwordController.text.trim();

    final validationMessage = InputValidation.validateCaregiverInputs(
      isRegistration: registering,
      name: name,
      phoneOrEmail: phoneOrEmail,
      password: password,
      verificationChannel: registering ? verificationChannel : null,
    );
    if (validationMessage != null) {
      _showMessage(validationMessage);
      return;
    }

    if (!_submissionGuard.tryStart()) return;
    setState(() {});

    try {
      if (registering) {
        final result = await ApiService.registerCaregiver(
          name: name,
          phoneOrEmail: phoneOrEmail,
          password: password,
          channel: verificationChannel,
        );

        if (!mounted) return;
        await _openPendingVerification(result.pendingVerification);
      } else {
        final result = await ApiService.loginCaregiver(
          phoneOrEmail: phoneOrEmail,
          password: password,
        );

        if (!mounted) return;
        await SessionService.saveCaregiverSession(
          caregiverId: result.caregiverId,
          caregiverName: result.caregiverName,
          authToken: result.accessToken,
        );

        if (!mounted) return;
        _showMessage('Login successful.');
        _goToDashboard();
      }
    } on VerificationApiException catch (error) {
      final pending = error.pendingVerification;
      if (error.code == 'verification_required' && pending != null) {
        await _openPendingVerification(pending);
      } else if (mounted) {
        _showMessage(error.message);
      }
    } catch (error) {
      if (!mounted) return;

      _showMessage(
        error is ApiException
            ? error.message
            : 'Could not complete authentication. Please try again.',
      );
    } finally {
      _submissionGuard.finish();
      if (mounted) setState(() {});
    }
  }

  Future<void> _openPendingVerification(
    PendingVerificationContext pending,
  ) async {
    await SessionService.savePendingVerification(pending);
    if (!mounted) return;

    Navigator.pushReplacement(
      context,
      MaterialPageRoute(
        builder: (_) => CaregiverOtpVerificationScreen(pending: pending),
      ),
    );
  }

  void _goToDashboard() {
    Navigator.pushReplacement(
      context,
      MaterialPageRoute(builder: (_) => const CaregiverDashboardScreen()),
    );
  }

  void _showMessage(String message) {
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  void _toggleMode() {
    setState(() {
      isRegisterMode = !isRegisterMode;
    });
  }

  @override
  Widget build(BuildContext context) {
    final strings = AppStrings.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(
          isRegisterMode ? strings.caregiverRegister : strings.caregiverLogin,
        ),
        actions: const [
          LanguageToggleButton(),
          SizedBox(width: AppSpacing.xs),
        ],
      ),
      body: ResponsiveContent(
        maxWidth: AppSpacing.formMaxWidth,
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
        child: SingleChildScrollView(
          keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 24),

              Container(
                padding: const EdgeInsets.all(18),
                decoration: BoxDecoration(
                  color: AppColors.mint,
                  borderRadius: BorderRadius.circular(24),
                ),
                child: Icon(
                  Icons.family_restroom_rounded,
                  size: 62,
                  color: AppColors.primary,
                ),
              ),

              const SizedBox(height: 22),

              Text(
                isRegisterMode ? 'Create Caregiver Account' : 'Welcome Back',
                style: TextStyle(
                  fontSize: 29,
                  fontWeight: FontWeight.w900,
                  color: AppColors.textDark,
                ),
              ),

              const SizedBox(height: 8),

              Text(
                isRegisterMode
                    ? 'Register as a caregiver, then verify ownership of your email address or phone number before logging in.'
                    : 'Login to continue managing elderly patient health records.',
                style: TextStyle(
                  height: 1.6,
                  color: AppColors.textSoft,
                  fontWeight: FontWeight.w500,
                ),
              ),

              const SizedBox(height: 30),

              if (isRegisterMode) ...[
                TextField(
                  controller: nameController,
                  key: const Key('caregiver-name-input'),
                  textInputAction: TextInputAction.next,
                  autofillHints: const [AutofillHints.name],
                  decoration: const InputDecoration(
                    labelText: 'Caregiver name',
                    prefixIcon: Icon(Icons.person_outline_rounded),
                  ),
                ),
                const SizedBox(height: 14),
                Text(
                  'Verify using',
                  style: TextStyle(
                    color: AppColors.textDark,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 8),
                SegmentedButton<CaregiverVerificationChannel>(
                  key: const Key('caregiver-verification-channel'),
                  segments: const [
                    ButtonSegment(
                      value: CaregiverVerificationChannel.email,
                      label: Text('Email'),
                      icon: Icon(Icons.email_outlined),
                    ),
                    ButtonSegment(
                      value: CaregiverVerificationChannel.sms,
                      label: Text('SMS'),
                      icon: Icon(Icons.sms_outlined),
                    ),
                  ],
                  selected: {verificationChannel},
                  onSelectionChanged: isLoading
                      ? null
                      : (selection) {
                          if (selection.isEmpty) return;
                          setState(() {
                            verificationChannel = selection.first;
                            phoneController.clear();
                          });
                        },
                ),
                const SizedBox(height: 14),
              ],

              TextField(
                key: const Key('caregiver-identity-input'),
                controller: phoneController,
                keyboardType: isRegisterMode
                    ? verificationChannel == CaregiverVerificationChannel.email
                          ? TextInputType.emailAddress
                          : TextInputType.phone
                    : TextInputType.emailAddress,
                autocorrect: false,
                textCapitalization: TextCapitalization.none,
                textInputAction: TextInputAction.next,
                autofillHints: isRegisterMode
                    ? verificationChannel == CaregiverVerificationChannel.email
                          ? const [AutofillHints.email]
                          : const [AutofillHints.telephoneNumber]
                    : const [AutofillHints.username],
                decoration: InputDecoration(
                  labelText: isRegisterMode
                      ? verificationChannel ==
                                CaregiverVerificationChannel.email
                            ? 'Email address'
                            : 'Phone number (+country code)'
                      : 'Email or phone',
                  helperText:
                      isRegisterMode &&
                          verificationChannel ==
                              CaregiverVerificationChannel.sms
                      ? 'Use international format, for example +8801712345678.'
                      : null,
                  prefixIcon: Icon(
                    isRegisterMode &&
                            verificationChannel ==
                                CaregiverVerificationChannel.sms
                        ? Icons.phone_outlined
                        : Icons.mail_outline_rounded,
                  ),
                ),
              ),

              const SizedBox(height: 14),

              TextField(
                key: const Key('caregiver-password-input'),
                controller: passwordController,
                obscureText: true,
                textInputAction: TextInputAction.done,
                autofillHints: const [AutofillHints.password],
                onSubmitted: isLoading ? null : (_) => _submit(),
                decoration: const InputDecoration(
                  labelText: 'Password',
                  prefixIcon: Icon(Icons.lock_outline_rounded),
                ),
              ),

              const SizedBox(height: 28),

              if (isLoading)
                Center(
                  child: Semantics(
                    label: strings.loading,
                    liveRegion: true,
                    child: const CircularProgressIndicator(),
                  ),
                )
              else
                PrimaryButton(
                  text: isRegisterMode
                      ? '${strings.register} & Continue'
                      : '${strings.login} & Continue',
                  icon: Icons.arrow_forward_rounded,
                  onPressed: _submit,
                ),

              const SizedBox(height: 18),

              Center(
                child: TextButton(
                  onPressed: isLoading ? null : _toggleMode,
                  child: Text(
                    isRegisterMode
                        ? 'Already have an account? Login'
                        : 'New caregiver? Register',
                    style: TextStyle(
                      fontWeight: FontWeight.w800,
                      color: AppColors.primary,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
