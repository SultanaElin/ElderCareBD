import 'package:flutter/material.dart';

import '../services/session_service.dart';
import '../utils/app_colors.dart';
import '../utils/app_spacing.dart';
import 'caregiver_otp_verification_screen.dart';
import 'role_selection_screen.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  @override
  void initState() {
    super.initState();
    _routeAfterSplash();
  }

  Future<void> _routeAfterSplash() async {
    final pendingFuture = SessionService.getPendingVerification();
    await Future<void>.delayed(const Duration(seconds: 2));

    try {
      final pending = await pendingFuture;
      if (!mounted) return;
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(
          builder: (_) => pending == null
              ? const RoleSelectionScreen()
              : CaregiverOtpVerificationScreen(pending: pending),
        ),
      );
    } catch (_) {
      if (!mounted) return;
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(builder: (_) => const RoleSelectionScreen()),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Semantics(
        label: 'ElderCare BD is starting',
        child: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.all(AppSpacing.lg),
                decoration: const BoxDecoration(
                  color: AppColors.mint,
                  shape: BoxShape.circle,
                ),
                child: const Icon(
                  Icons.health_and_safety_rounded,
                  color: AppColors.primary,
                  size: 82,
                ),
              ),
              const SizedBox(height: AppSpacing.lg),
              Text(
                'ElderCare BD',
                style: Theme.of(context).textTheme.headlineLarge?.copyWith(
                  color: AppColors.textDark,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                'Care • Screen • Support',
                style: Theme.of(
                  context,
                ).textTheme.bodyLarge?.copyWith(color: AppColors.textSoft),
              ),
              const SizedBox(height: AppSpacing.lg),
              const SizedBox(
                width: 32,
                height: 32,
                child: CircularProgressIndicator(strokeWidth: 3),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
