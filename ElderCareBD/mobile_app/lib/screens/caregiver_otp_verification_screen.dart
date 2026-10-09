import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../models/caregiver_verification.dart';
import '../services/api_service.dart';
import '../services/session_service.dart';
import '../utils/app_colors.dart';
import '../utils/app_spacing.dart';
import '../utils/app_strings.dart';
import '../utils/input_validation.dart';
import '../widgets/app_card.dart';
import '../widgets/language_toggle_button.dart';
import '../widgets/primary_button.dart';
import '../widgets/responsive_content.dart';
import 'caregiver_login_screen.dart';

class CaregiverOtpVerificationScreen extends StatefulWidget {
  const CaregiverOtpVerificationScreen({super.key, required this.pending});

  final PendingVerificationContext pending;

  @override
  State<CaregiverOtpVerificationScreen> createState() =>
      _CaregiverOtpVerificationScreenState();
}

class _CaregiverOtpVerificationScreenState
    extends State<CaregiverOtpVerificationScreen> {
  final _otpController = TextEditingController();
  Timer? _timer;
  late PendingVerificationContext _pending;
  DateTime _now = DateTime.now().toUtc();
  String? _feedback;
  String? _feedbackCode;
  bool _isVerifying = false;
  bool _isResending = false;

  @override
  void initState() {
    super.initState();
    _pending = widget.pending;
    _ensureTimer();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _otpController.dispose();
    super.dispose();
  }

  int _secondsUntil(DateTime value) {
    final milliseconds = value.difference(_now).inMilliseconds;
    if (milliseconds <= 0) return 0;
    return (milliseconds / Duration.millisecondsPerSecond).ceil();
  }

  int get _expirySeconds => _secondsUntil(_pending.expiresAt);
  int get _resendSeconds => _secondsUntil(_pending.resendAvailableAt);

  String _formatDuration(int totalSeconds) {
    final minutes = totalSeconds ~/ 60;
    final seconds = totalSeconds % 60;
    return '${minutes.toString().padLeft(2, '0')}:${seconds.toString().padLeft(2, '0')}';
  }

  void _ensureTimer() {
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) return;
      setState(() => _now = DateTime.now().toUtc());
      if (_expirySeconds == 0 && _resendSeconds == 0) timer.cancel();
    });
  }

  Future<void> _verify() async {
    final otp = _otpController.text.trim();
    final validationMessage = InputValidation.validateOtp(otp);
    if (validationMessage != null) {
      _setFeedback('invalid_input', validationMessage);
      return;
    }
    if (_isVerifying || _isResending) return;

    setState(() {
      _isVerifying = true;
      _feedback = null;
      _feedbackCode = null;
    });

    try {
      await ApiService.verifyCaregiverOtp(
        caregiverId: _pending.caregiverId,
        channel: _pending.channel,
        otp: otp,
      );
      await SessionService.clearPendingVerification();
      if (!mounted) return;
      _showMessage('Verification successful. Please log in.');
      _goToLogin();
    } on VerificationApiException catch (error) {
      if (error.code == 'already_verified' ||
          error.code == 'caregiver_already_verified') {
        await SessionService.clearPendingVerification();
        if (!mounted) return;
        _showMessage('This account is verified. Please log in.');
        _goToLogin();
      } else if (mounted) {
        _setFeedback(error.code, error.message);
      }
    } on ApiException catch (error) {
      if (mounted) _setFeedback('request_failed', error.message);
    } catch (_) {
      if (mounted) {
        _setFeedback(
          'request_failed',
          'Verification could not be completed. Please try again.',
        );
      }
    } finally {
      if (mounted) setState(() => _isVerifying = false);
    }
  }

  Future<void> _resend() async {
    if (_resendSeconds > 0 || _isVerifying || _isResending) return;

    setState(() {
      _isResending = true;
      _feedback = null;
      _feedbackCode = null;
    });

    try {
      final result = await ApiService.resendCaregiverOtp(
        caregiverId: _pending.caregiverId,
        channel: _pending.channel,
      );
      final replacement = result.pendingVerification;
      await SessionService.savePendingVerification(replacement);
      if (!mounted) return;
      setState(() {
        _pending = replacement;
        _now = DateTime.now().toUtc();
        _otpController.clear();
        _feedbackCode = 'resend_success';
        _feedback = 'A new verification code was sent.';
      });
      _ensureTimer();
    } on VerificationApiException catch (error) {
      if (error.code == 'already_verified' ||
          error.code == 'caregiver_already_verified') {
        await SessionService.clearPendingVerification();
        if (!mounted) return;
        _showMessage('This account is verified. Please log in.');
        _goToLogin();
        return;
      }

      var replacement = error.pendingVerification;
      if (replacement == null &&
          (error.code == 'resend_cooldown' ||
              error.code == 'otp_resend_cooldown') &&
          error.retryAfterSeconds != null) {
        replacement = _pending.copyWith(
          resendAvailableAt: DateTime.now().toUtc().add(
            Duration(seconds: error.retryAfterSeconds!),
          ),
        );
      }
      if (replacement != null) {
        await SessionService.savePendingVerification(replacement);
        if (!mounted) return;
        setState(() {
          _pending = replacement!;
          _now = DateTime.now().toUtc();
        });
        _ensureTimer();
      }
      if (mounted) _setFeedback(error.code, error.message);
    } on ApiException catch (error) {
      if (mounted) _setFeedback('request_failed', error.message);
    } catch (_) {
      if (mounted) {
        _setFeedback(
          'request_failed',
          'A new verification code could not be sent. Please try again.',
        );
      }
    } finally {
      if (mounted) setState(() => _isResending = false);
    }
  }

  void _setFeedback(String code, String message) {
    setState(() {
      _feedbackCode = code;
      _feedback = message;
    });
  }

  void _showMessage(String message) {
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  void _goToLogin() {
    Navigator.pushReplacement(
      context,
      MaterialPageRoute(
        builder: (_) => const CaregiverLoginScreen(initialRegisterMode: false),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final strings = AppStrings.of(context);
    final expired = _expirySeconds == 0;
    final busy = _isVerifying || _isResending;

    return Scaffold(
      appBar: AppBar(
        title: Text(strings.verifyCaregiverAccount),
        actions: const [
          LanguageToggleButton(),
          SizedBox(width: AppSpacing.xs),
        ],
      ),
      body: ResponsiveContent(
        maxWidth: 620,
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
        child: SingleChildScrollView(
          keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 18),
              const Icon(
                Icons.verified_user_outlined,
                size: 68,
                color: AppColors.primary,
              ),
              const SizedBox(height: 18),
              Text(
                'Enter the six-digit code',
                style: TextStyle(
                  fontSize: 27,
                  fontWeight: FontWeight.w900,
                  color: AppColors.textDark,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'A verification code was sent by ${_pending.channel.displayLabel} to ${_pending.destinationHint}. Do not share this code with anyone.',
                key: const Key('otp-destination-message'),
                style: TextStyle(color: AppColors.textSoft, height: 1.5),
              ),
              const SizedBox(height: 22),
              AppCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    TextField(
                      key: const Key('caregiver-otp-input'),
                      controller: _otpController,
                      enabled: !busy,
                      keyboardType: TextInputType.number,
                      textInputAction: TextInputAction.done,
                      maxLength: 6,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        fontSize: 28,
                        letterSpacing: 12,
                        fontWeight: FontWeight.w800,
                      ),
                      autofillHints: const [AutofillHints.oneTimeCode],
                      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                      onSubmitted: (_) => _verify(),
                      decoration: const InputDecoration(
                        labelText: 'Verification code',
                        hintText: '000000',
                        prefixIcon: Icon(Icons.password_rounded),
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      expired
                          ? 'This code may have expired. Request a new code.'
                          : 'Code expires in ${_formatDuration(_expirySeconds)}',
                      key: const Key('otp-expiry-status'),
                      style: TextStyle(
                        color: expired ? AppColors.warning : AppColors.textSoft,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    if (_feedback != null) ...[
                      const SizedBox(height: 12),
                      Semantics(
                        liveRegion: true,
                        child: Text(
                          _feedback!,
                          key: ValueKey(
                            'otp-feedback-${_feedbackCode ?? 'status'}',
                          ),
                          style: TextStyle(
                            color: _feedbackCode == 'resend_success'
                                ? AppColors.success
                                : AppColors.danger,
                            height: 1.4,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: 20),
              if (_isVerifying)
                Center(
                  child: Semantics(
                    label: 'Verifying code',
                    liveRegion: true,
                    child: CircularProgressIndicator(),
                  ),
                )
              else
                PrimaryButton(
                  text: strings.verifyCode,
                  icon: Icons.check_circle_outline_rounded,
                  onPressed: _verify,
                ),
              const SizedBox(height: 12),
              Center(
                child: _isResending
                    ? const Padding(
                        padding: EdgeInsets.all(12),
                        child: CircularProgressIndicator(),
                      )
                    : TextButton.icon(
                        key: const Key('resend-otp-button'),
                        onPressed: busy || _resendSeconds > 0 ? null : _resend,
                        icon: const Icon(Icons.refresh_rounded),
                        label: Text(
                          _resendSeconds > 0
                              ? 'Resend code in ${_formatDuration(_resendSeconds)}'
                              : strings.resendOtp,
                        ),
                      ),
              ),
              Center(
                child: TextButton(
                  onPressed: busy ? null : _goToLogin,
                  child: const Text('Return to caregiver login'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
