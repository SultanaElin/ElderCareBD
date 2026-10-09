import 'package:flutter/material.dart';

import '../services/api_service.dart';
import '../services/session_service.dart';
import '../utils/app_colors.dart';
import '../utils/app_strings.dart';
import '../utils/input_validation.dart';
import '../widgets/app_card.dart';
import '../widgets/responsive_content.dart';
import '../widgets/section_header.dart';
import 'assessment_screen.dart';
import 'daily_health_update_screen.dart';
import 'health_trends_screen.dart';
import 'history_screen.dart';
import 'medicine_tracker_screen.dart';
import 'patient_profile_screen.dart';
import 'prescription_input_screen.dart';
import 'role_selection_screen.dart';

class CaregiverDashboardScreen extends StatefulWidget {
  const CaregiverDashboardScreen({super.key});

  @override
  State<CaregiverDashboardScreen> createState() =>
      _CaregiverDashboardScreenState();
}

class _CaregiverDashboardScreenState extends State<CaregiverDashboardScreen> {
  bool isLoading = true;

  int? caregiverId;
  String caregiverName = 'Caregiver';

  int? patientId;
  String patientName = 'No patient selected';

  List<dynamic> patients = [];
  List<dynamic> assessments = [];
  List<dynamic> medicines = [];

  String latestRisk = 'No assessment yet';
  String latestGlucose = 'N/A';
  String latestBp = 'N/A';
  int alertCount = 0;

  @override
  void initState() {
    super.initState();
    _loadDashboardData();
  }

  Future<void> _loadDashboardData() async {
    setState(() {
      isLoading = true;
    });

    try {
      final savedCaregiverId = await SessionService.getCaregiverId();
      final savedCaregiverName = await SessionService.getCaregiverName();

      final savedPatientId = await SessionService.getSelectedPatientId();
      final savedPatientName = await SessionService.getSelectedPatientName();

      if (savedCaregiverId == null) {
        setState(() {
          caregiverId = null;
          caregiverName = 'Caregiver';
          patientId = null;
          patientName = 'Please login first';
          patients = [];
          assessments = [];
          medicines = [];
          latestRisk = 'No assessment yet';
          latestGlucose = 'N/A';
          latestBp = 'N/A';
          alertCount = 0;
          isLoading = false;
        });
        return;
      }

      final caregiverPatients = await ApiService.getPatientsByCaregiver(
        caregiverId: savedCaregiverId,
      );

      int? activePatientId = savedPatientId;
      String? activePatientName = savedPatientName;

      final selectedBelongsToCaregiver = caregiverPatients.any((p) {
        final patient = Map<String, dynamic>.from(p);
        return patient['id'] == savedPatientId;
      });

      if (activePatientId != null && !selectedBelongsToCaregiver) {
        activePatientId = null;
        activePatientName = null;
      }

      if (activePatientId == null && caregiverPatients.isNotEmpty) {
        final firstPatient = Map<String, dynamic>.from(caregiverPatients.first);

        activePatientId = firstPatient['id'];
        activePatientName = firstPatient['name']?.toString();

        await SessionService.saveSelectedPatient(
          patientId: activePatientId!,
          patientName: activePatientName ?? 'Selected Patient',
        );
      }

      List<dynamic> patientAssessments = [];
      List<dynamic> patientMedicines = [];

      if (activePatientId != null) {
        patientAssessments = await ApiService.getPatientAssessments(
          patientId: activePatientId,
        );

        patientMedicines = await ApiService.getPatientMedicines(
          patientId: activePatientId,
        );
      }

      final latestAssessment = _getLatestRecord(patientAssessments);

      setState(() {
        caregiverId = savedCaregiverId;
        caregiverName = savedCaregiverName ?? 'Caregiver';

        patientId = activePatientId;
        patientName = activePatientName ?? 'No patient selected';

        patients = caregiverPatients;
        assessments = patientAssessments;
        medicines = patientMedicines;

        if (latestAssessment != null) {
          latestRisk = latestAssessment['overall_risk']?.toString() ?? 'N/A';
          latestGlucose = InputValidation.formatStoredGlucoseMmolL(
            latestAssessment['glucose'],
          );
          latestBp =
              '${latestAssessment['systolic_bp'] ?? 'N/A'}/${latestAssessment['diastolic_bp'] ?? 'N/A'}';
        } else {
          latestRisk = 'No assessment yet';
          latestGlucose = 'N/A';
          latestBp = 'N/A';
        }

        alertCount = _countMedicineAlerts(patientMedicines);
        isLoading = false;
      });
    } catch (e) {
      setState(() {
        caregiverId = null;
        caregiverName = 'Caregiver';
        patientId = null;
        patientName = 'Data loading failed';
        patients = [];
        assessments = [];
        medicines = [];
        latestRisk = 'Unavailable';
        latestGlucose = 'N/A';
        latestBp = 'N/A';
        alertCount = 0;
        isLoading = false;
      });

      if (!mounted) return;

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Dashboard data could not be loaded. Check your connection and try again.',
          ),
        ),
      );
    }
  }

  Map<String, dynamic>? _getLatestRecord(List<dynamic> records) {
    if (records.isEmpty) return null;

    final copied = records.map((e) => Map<String, dynamic>.from(e)).toList();

    copied.sort((a, b) {
      final aDate = DateTime.tryParse(a['created_at']?.toString() ?? '');
      final bDate = DateTime.tryParse(b['created_at']?.toString() ?? '');

      if (aDate == null || bDate == null) return 0;
      return bDate.compareTo(aDate);
    });

    return copied.first;
  }

  int _countMedicineAlerts(List<dynamic> items) {
    int count = 0;

    for (final item in items) {
      final medicine = Map<String, dynamic>.from(item);
      final rawDate = medicine['run_out_date'];

      if (rawDate == null || rawDate.toString().isEmpty) continue;

      final runOutDate = DateTime.tryParse(rawDate.toString());
      if (runOutDate == null) continue;

      final remainingDays = runOutDate.difference(DateTime.now()).inDays;

      if (remainingDays <= 7) {
        count++;
      }
    }

    return count;
  }

  Color _riskColor(String risk) {
    if (risk == 'High') return AppColors.danger;
    if (risk == 'Medium') return AppColors.warning;
    if (risk == 'Low') return AppColors.success;
    return AppColors.primary;
  }

  void _go(BuildContext context, Widget screen) async {
    await Navigator.push(context, MaterialPageRoute(builder: (_) => screen));

    _loadDashboardData();
  }

  void _onDestinationSelected(int index) {
    switch (index) {
      case 1:
        _go(context, const AssessmentScreen());
      case 2:
        _go(context, const MedicineTrackerScreen());
      case 3:
        _go(context, const HistoryScreen());
    }
  }

  Future<void> _logout() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Log out?'),
        content: const Text(
          'You will need to enter your caregiver credentials again.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Log out'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    await SessionService.clearSession();
    if (!mounted) return;
    Navigator.pushAndRemoveUntil(
      context,
      MaterialPageRoute(builder: (_) => const RoleSelectionScreen()),
      (_) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    final riskColor = _riskColor(latestRisk);
    final strings = AppStrings.of(context);

    return Scaffold(
      bottomNavigationBar: NavigationBar(
        selectedIndex: 0,
        onDestinationSelected: _onDestinationSelected,
        destinations: [
          NavigationDestination(
            icon: const Icon(Icons.dashboard_rounded),
            label: strings.dashboard,
          ),
          NavigationDestination(
            icon: const Icon(Icons.monitor_heart_rounded),
            label: strings.assessment,
          ),
          NavigationDestination(
            icon: const Icon(Icons.medication_rounded),
            label: 'Medicine',
          ),
          NavigationDestination(
            icon: const Icon(Icons.history_rounded),
            label: strings.history,
          ),
        ],
      ),
      body: ResponsiveContent(
        padding: EdgeInsets.zero,
        child: RefreshIndicator(
          onRefresh: _loadDashboardData,
          child: SingleChildScrollView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(20, 18, 20, 24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _Header(
                  caregiverName: caregiverName,
                  caregiverId: caregiverId,
                  isLoading: isLoading,
                  onRefresh: _loadDashboardData,
                  onLogout: _logout,
                ),
                const SizedBox(height: 20),

                _HeroHealthCard(
                  patientName: patientName,
                  patientId: patientId,
                  latestRisk: latestRisk,
                  latestGlucose: latestGlucose,
                  latestBp: latestBp,
                  riskColor: riskColor,
                  isLoading: isLoading,
                ),

                const SizedBox(height: 20),

                const SectionHeader(
                  title: 'Quick actions',
                  subtitle: 'Caregiver-specific patient care workflow',
                ),
                const SizedBox(height: 14),

                LayoutBuilder(
                  builder: (context, constraints) {
                    final largeText =
                        MediaQuery.textScalerOf(context).scale(1) >= 1.4;
                    final columns = constraints.maxWidth >= 760
                        ? 3
                        : (constraints.maxWidth < 420 || largeText ? 1 : 2);
                    final aspectRatio = columns == 1
                        ? 2.25
                        : (constraints.maxWidth >= 760 ? 1.55 : 1.05);
                    return GridView.count(
                      crossAxisCount: columns,
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      mainAxisSpacing: 14,
                      crossAxisSpacing: 14,
                      childAspectRatio: aspectRatio,
                      children: [
                        _ActionCard(
                          title: strings.patients,
                          subtitle: 'Create or update',
                          icon: Icons.elderly_rounded,
                          color: AppColors.primary,
                          onTap: () =>
                              _go(context, const PatientProfileScreen()),
                        ),
                        _ActionCard(
                          title: strings.assessment,
                          subtitle: 'Predict risk',
                          icon: Icons.monitor_heart_rounded,
                          color: AppColors.secondary,
                          onTap: () => _go(context, const AssessmentScreen()),
                        ),
                        _ActionCard(
                          title: "Today's Health Update",
                          subtitle: 'Record daily observations',
                          icon: Icons.health_and_safety_outlined,
                          color: AppColors.success,
                          onTap: () =>
                              _go(context, const DailyHealthUpdateScreen()),
                        ),
                        _ActionCard(
                          title: '7-Day Health Trends',
                          subtitle: 'View recent measurements',
                          icon: Icons.show_chart_rounded,
                          color: AppColors.info,
                          onTap: () =>
                              _go(context, const HealthTrendsScreen()),
                        ),
                        _ActionCard(
                          title: strings.prescription,
                          subtitle: 'Add medicines',
                          icon: Icons.receipt_long_rounded,
                          color: AppColors.purple,
                          onTap: () =>
                              _go(context, const PrescriptionInputScreen()),
                        ),
                        _ActionCard(
                          title: 'Medicine tracker',
                          subtitle: 'Restock planning',
                          icon: Icons.medication_liquid_rounded,
                          color: AppColors.warning,
                          onTap: () =>
                              _go(context, const MedicineTrackerScreen()),
                        ),
                        _ActionCard(
                          title: strings.history,
                          subtitle: 'Saved records',
                          icon: Icons.history_edu_rounded,
                          color: AppColors.info,
                          onTap: () => _go(context, const HistoryScreen()),
                        ),
                      ],
                    );
                  },
                ),

                const SizedBox(height: 20),

                const SectionHeader(
                  title: 'Caregiver overview',
                  subtitle:
                      'Only patients under the logged-in caregiver are counted',
                ),
                const SizedBox(height: 14),

                Row(
                  children: [
                    Expanded(
                      child: _MiniStatCard(
                        title: 'My Patients',
                        value: patients.length.toString(),
                        icon: Icons.groups_rounded,
                        color: AppColors.primary,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: _MiniStatCard(
                        title: 'Alerts',
                        value: alertCount.toString(),
                        icon: Icons.notifications_active_rounded,
                        color: AppColors.warning,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),

                Row(
                  children: [
                    Expanded(
                      child: _MiniStatCard(
                        title: 'Assessments',
                        value: assessments.length.toString(),
                        icon: Icons.analytics_rounded,
                        color: AppColors.secondary,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: _MiniStatCard(
                        title: 'Medicines',
                        value: medicines.length.toString(),
                        icon: Icons.medication_rounded,
                        color: AppColors.purple,
                      ),
                    ),
                  ],
                ),

                const SizedBox(height: 18),

                _PatientListCard(
                  patients: patients,
                  activePatientId: patientId,
                  onSelect: (selectedPatient) async {
                    final id = selectedPatient['id'];
                    final name =
                        selectedPatient['name']?.toString() ??
                        'Selected Patient';

                    if (id == null) return;

                    await SessionService.saveSelectedPatient(
                      patientId: id,
                      patientName: name,
                    );

                    _loadDashboardData();
                  },
                ),

                const SizedBox(height: 18),

                _RestockAlertCard(alertCount: alertCount),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  final String caregiverName;
  final int? caregiverId;
  final bool isLoading;
  final VoidCallback onRefresh;
  final VoidCallback onLogout;

  const _Header({
    required this.caregiverName,
    required this.caregiverId,
    required this.isLoading,
    required this.onRefresh,
    required this.onLogout,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                isLoading ? 'Loading dashboard...' : 'Good day, $caregiverName',
                style: TextStyle(
                  color: AppColors.textSoft,
                  fontWeight: FontWeight.w500,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                caregiverId == null
                    ? 'Caregiver Dashboard'
                    : 'Caregiver Dashboard • ID: $caregiverId',
                style: TextStyle(
                  fontSize: 25,
                  fontWeight: FontWeight.w900,
                  color: AppColors.textDark,
                ),
              ),
            ],
          ),
        ),
        IconButton(
          onPressed: onRefresh,
          tooltip: 'Refresh dashboard',
          icon: const Icon(Icons.refresh_rounded),
        ),
        IconButton(
          onPressed: onLogout,
          tooltip: 'Log out',
          icon: const Icon(Icons.logout_rounded),
        ),
      ],
    );
  }
}

class _HeroHealthCard extends StatelessWidget {
  final String patientName;
  final int? patientId;
  final String latestRisk;
  final String latestGlucose;
  final String latestBp;
  final Color riskColor;
  final bool isLoading;

  const _HeroHealthCard({
    required this.patientName,
    required this.patientId,
    required this.latestRisk,
    required this.latestGlucose,
    required this.latestBp,
    required this.riskColor,
    required this.isLoading,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(22),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(28),
        color: AppColors.primaryDark,
      ),
      child: isLoading
          ? const Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: CircularProgressIndicator(color: Colors.white),
              ),
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(
                  Icons.health_and_safety_rounded,
                  color: Colors.white,
                  size: 56,
                ),
                const SizedBox(height: 14),
                Text(
                  patientId == null
                      ? 'No patient selected'
                      : '$patientName • Patient ID: $patientId',
                  style: TextStyle(
                    color: Colors.white70,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  latestRisk,
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 30,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  latestRisk == 'No assessment yet'
                      ? 'Create/select a patient under this caregiver and complete health assessment.'
                      : 'Latest health status for the selected patient only.',
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.88),
                    height: 1.5,
                    fontSize: 13,
                  ),
                ),
                const SizedBox(height: 16),
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    _TopChip(label: 'Glucose', value: latestGlucose),
                    _TopChip(label: 'BP', value: latestBp),
                    _TopChip(label: 'Risk', value: latestRisk),
                  ],
                ),
              ],
            ),
    );
  }
}

class _TopChip extends StatelessWidget {
  final String label;
  final String value;

  const _TopChip({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(18),
      ),
      child: Text(
        '$label: $value',
        overflow: TextOverflow.ellipsis,
        style: TextStyle(
          color: Colors.white,
          fontWeight: FontWeight.w700,
          fontSize: 12,
        ),
      ),
    );
  }
}

class _ActionCard extends StatelessWidget {
  final String title;
  final String subtitle;
  final IconData icon;
  final Color color;
  final VoidCallback onTap;

  const _ActionCard({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return AppCard(
      onTap: onTap,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CircleAvatar(
            radius: 24,
            backgroundColor: color.withValues(alpha: 0.14),
            child: Icon(icon, color: color, size: 24),
          ),
          const Spacer(),
          Text(
            title,
            style: TextStyle(
              color: AppColors.textDark,
              fontSize: 16,
              height: 1.18,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            subtitle,
            style: TextStyle(color: AppColors.textSoft, fontSize: 12.5),
          ),
        ],
      ),
    );
  }
}

class _MiniStatCard extends StatelessWidget {
  final String title;
  final String value;
  final IconData icon;
  final Color color;

  const _MiniStatCard({
    required this.title,
    required this.value,
    required this.icon,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Row(
        children: [
          CircleAvatar(
            backgroundColor: color.withValues(alpha: 0.12),
            child: Icon(icon, color: color),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  value,
                  style: TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.w900,
                    color: AppColors.textDark,
                  ),
                ),
                Text(
                  title,
                  style: TextStyle(fontSize: 12.5, color: AppColors.textSoft),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _PatientListCard extends StatelessWidget {
  final List<dynamic> patients;
  final int? activePatientId;
  final Future<void> Function(Map<String, dynamic>) onSelect;

  const _PatientListCard({
    required this.patients,
    required this.activePatientId,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'My patient list',
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w900,
              color: AppColors.textDark,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'Only patients created under the logged-in caregiver are shown here.',
            style: TextStyle(color: AppColors.textSoft, height: 1.45),
          ),
          const SizedBox(height: 14),
          if (patients.isEmpty)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: AppColors.mint,
                borderRadius: BorderRadius.circular(16),
              ),
              child: Text(
                'No patient found for this caregiver. Create a patient profile first.',
                style: TextStyle(
                  color: AppColors.textDark,
                  fontWeight: FontWeight.w600,
                ),
              ),
            )
          else
            ...patients.map((item) {
              final patient = Map<String, dynamic>.from(item);
              final id = patient['id'];
              final name = patient['name']?.toString() ?? 'Unknown';
              final age = patient['age']?.toString() ?? 'N/A';
              final isSelected = id == activePatientId;

              return Container(
                margin: const EdgeInsets.only(bottom: 10),
                decoration: BoxDecoration(
                  color: isSelected ? AppColors.mint : Colors.white,
                  borderRadius: BorderRadius.circular(18),
                  border: Border.all(
                    color: isSelected ? AppColors.primary : AppColors.border,
                    width: isSelected ? 1.4 : 1,
                  ),
                ),
                child: ListTile(
                  leading: CircleAvatar(
                    backgroundColor: isSelected
                        ? AppColors.primary
                        : AppColors.mint,
                    child: Icon(
                      Icons.elderly_rounded,
                      color: isSelected ? Colors.white : AppColors.primary,
                    ),
                  ),
                  title: Text(
                    name,
                    style: TextStyle(
                      fontWeight: FontWeight.w900,
                      color: AppColors.textDark,
                    ),
                  ),
                  subtitle: Text(
                    'Patient ID: $id • Age: $age',
                    style: TextStyle(color: AppColors.textSoft),
                  ),
                  trailing: isSelected
                      ? const Icon(
                          Icons.check_circle_rounded,
                          color: AppColors.success,
                        )
                      : const Icon(Icons.chevron_right_rounded),
                  onTap: () => onSelect(patient),
                ),
              );
            }),
        ],
      ),
    );
  }
}

class _RestockAlertCard extends StatelessWidget {
  final int alertCount;

  const _RestockAlertCard({required this.alertCount});

  @override
  Widget build(BuildContext context) {
    final message = alertCount > 0
        ? '$alertCount medicine(s) may need restock soon for the selected patient.'
        : 'No urgent medicine restock alert found for the selected patient.';

    return AppCard(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CircleAvatar(
            backgroundColor: alertCount > 0
                ? AppColors.warning
                : AppColors.success,
            child: Icon(
              alertCount > 0
                  ? Icons.notifications_active_rounded
                  : Icons.verified_rounded,
              color: Colors.white,
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Text(
              message,
              style: TextStyle(
                color: AppColors.textDark,
                height: 1.45,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
