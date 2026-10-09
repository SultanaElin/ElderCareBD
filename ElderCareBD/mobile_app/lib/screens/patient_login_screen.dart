import 'package:flutter/material.dart';

import '../utils/app_colors.dart';
import '../utils/app_spacing.dart';
import '../widgets/primary_button.dart';
import '../widgets/responsive_content.dart';
import 'patient_dashboard_screen.dart';

class PatientLoginScreen extends StatelessWidget {
  const PatientLoginScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final patientCodeController = TextEditingController();

    return Scaffold(
      appBar: AppBar(title: const Text('Patient Login')),
      body: ResponsiveContent(
        maxWidth: AppSpacing.formMaxWidth,
        child: SingleChildScrollView(
          keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 24),
              const Icon(
                Icons.elderly_rounded,
                size: 76,
                color: AppColors.orange,
              ),
              const SizedBox(height: 20),
              Text(
                'Patient Access',
                style: TextStyle(
                  fontSize: 28,
                  fontWeight: FontWeight.w900,
                  color: AppColors.primary,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'Patients can view their health status, checkup recommendations, and medicine reminders.',
                style: TextStyle(height: 1.6, color: Colors.black54),
              ),
              const SizedBox(height: 28),
              TextField(
                controller: patientCodeController,
                decoration: const InputDecoration(
                  labelText: 'Patient code or phone',
                  prefixIcon: Icon(Icons.badge_outlined),
                ),
              ),
              const SizedBox(height: 28),
              PrimaryButton(
                text: 'Continue as Patient',
                icon: Icons.arrow_forward_rounded,
                onPressed: () {
                  Navigator.pushReplacement(
                    context,
                    MaterialPageRoute(
                      builder: (_) => const PatientDashboardScreen(),
                    ),
                  );
                },
              ),
            ],
          ),
        ),
      ),
    );
  }
}
