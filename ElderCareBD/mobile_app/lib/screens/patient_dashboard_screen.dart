import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../services/api_service.dart';
import '../services/session_service.dart';
import '../utils/app_colors.dart';
import '../utils/input_validation.dart';
import '../widgets/app_card.dart';
import '../widgets/responsive_content.dart';

class PatientDashboardScreen extends StatefulWidget {
  const PatientDashboardScreen({super.key});

  @override
  State<PatientDashboardScreen> createState() => _PatientDashboardScreenState();
}

class _PatientDashboardScreenState extends State<PatientDashboardScreen> {
  bool isLoading = true;
  String? errorMessage;

  int? patientId;
  Map<String, dynamic>? patient;
  List<dynamic> assessments = [];
  List<dynamic> medicines = [];

  @override
  void initState() {
    super.initState();
    _loadPatientDashboard();
  }

  Future<void> _loadPatientDashboard() async {
    setState(() {
      isLoading = true;
      errorMessage = null;
    });

    try {
      final savedPatientId = await SessionService.getSelectedPatientId();

      if (savedPatientId == null) {
        setState(() {
          isLoading = false;
          errorMessage =
              'No selected patient found. Please save a patient profile first.';
        });
        return;
      }

      final patientData = await ApiService.getPatientById(
        patientId: savedPatientId,
      );

      final assessmentData = await ApiService.getPatientAssessments(
        patientId: savedPatientId,
      );

      final medicineData = await ApiService.getPatientMedicines(
        patientId: savedPatientId,
      );

      setState(() {
        patientId = savedPatientId;
        patient = patientData;
        assessments = assessmentData;
        medicines = medicineData;
        isLoading = false;
      });
    } catch (_) {
      setState(() {
        isLoading = false;
        errorMessage =
            'Could not load the patient dashboard. Check your connection and try again.';
      });
    }
  }

  Map<String, dynamic>? _latestAssessment() {
    if (assessments.isEmpty) return null;

    final copied = assessments
        .map((e) => Map<String, dynamic>.from(e))
        .toList();

    copied.sort((a, b) {
      final aDate = DateTime.tryParse(a['created_at']?.toString() ?? '');
      final bDate = DateTime.tryParse(b['created_at']?.toString() ?? '');

      if (aDate == null || bDate == null) return 0;
      return bDate.compareTo(aDate);
    });

    return copied.first;
  }

  List<Map<String, dynamic>> _medicineAlerts() {
    final list = medicines.map((e) => Map<String, dynamic>.from(e)).toList();

    list.sort((a, b) {
      final aDate = DateTime.tryParse(a['run_out_date']?.toString() ?? '');
      final bDate = DateTime.tryParse(b['run_out_date']?.toString() ?? '');

      if (aDate == null && bDate == null) return 0;
      if (aDate == null) return 1;
      if (bDate == null) return -1;

      return aDate.compareTo(bDate);
    });

    return list.take(3).toList();
  }

  Color _riskColor(String risk) {
    if (risk == 'High') return AppColors.danger;
    if (risk == 'Medium') return AppColors.warning;
    if (risk == 'Low') return AppColors.success;
    return AppColors.primary;
  }

  String _conditionSummary() {
    if (patient == null) return 'No medical background available';

    final conditions = <String>[];

    if (patient!['has_diabetes'] == true) conditions.add('Diabetes');
    if (patient!['has_heart_disease'] == true) conditions.add('Heart Disease');
    if (patient!['has_hypertension'] == true) conditions.add('Hypertension');
    if (patient!['has_kidney_disease'] == true) {
      conditions.add('Kidney Disease');
    }
    if (patient!['has_stroke_history'] == true) {
      conditions.add('Stroke History');
    }

    if (conditions.isEmpty) return 'No major condition selected';
    return conditions.join(' • ');
  }

  int? _remainingDays(dynamic rawRunOutDate) {
    if (rawRunOutDate == null || rawRunOutDate.toString().isEmpty) return null;

    final date = DateTime.tryParse(rawRunOutDate.toString());
    if (date == null) return null;

    return date.difference(DateTime.now()).inDays;
  }

  String _formatDate(dynamic rawDate) {
    if (rawDate == null || rawDate.toString().isEmpty) return 'Not available';

    try {
      final date = DateTime.parse(rawDate.toString());
      return DateFormat('dd MMM yyyy').format(date);
    } catch (_) {
      return rawDate.toString();
    }
  }

  @override
  Widget build(BuildContext context) {
    final latest = _latestAssessment();

    final patientName = patient?['name']?.toString() ?? 'Patient';
    final patientAge = patient?['age']?.toString() ?? 'N/A';
    final emergencyContact =
        patient?['emergency_contact']?.toString().isNotEmpty == true
        ? patient!['emergency_contact'].toString()
        : 'Not added';

    final latestRisk =
        latest?['overall_risk']?.toString() ?? 'No assessment yet';
    final diabetesRisk = latest?['diabetes_risk']?.toString() ?? 'N/A';
    final heartRisk = latest?['heart_risk']?.toString() ?? 'N/A';
    final glucose = InputValidation.formatStoredGlucoseMmolL(
      latest?['glucose'],
    );
    final bp = latest == null
        ? 'N/A'
        : '${latest['systolic_bp'] ?? 'N/A'}/${latest['diastolic_bp'] ?? 'N/A'}';

    final riskColor = _riskColor(latestRisk);
    final alertMedicines = _medicineAlerts();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Patient Dashboard'),
        actions: [
          IconButton(
            onPressed: _loadPatientDashboard,
            tooltip: 'Refresh patient dashboard',
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
      body: ResponsiveContent(
        padding: EdgeInsets.zero,
        child: RefreshIndicator(
          onRefresh: _loadPatientDashboard,
          child: SingleChildScrollView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(22),
            child: isLoading
                ? const Center(
                    child: Padding(
                      padding: EdgeInsets.all(40),
                      child: CircularProgressIndicator(),
                    ),
                  )
                : errorMessage != null
                ? _ErrorCard(
                    message: errorMessage!,
                    onRetry: _loadPatientDashboard,
                  )
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _PatientHeader(
                        name: patientName,
                        age: patientAge,
                        conditionSummary: _conditionSummary(),
                      ),
                      const SizedBox(height: 22),

                      _HealthStatusCard(
                        latestRisk: latestRisk,
                        diabetesRisk: diabetesRisk,
                        heartRisk: heartRisk,
                        glucose: glucose,
                        bp: bp,
                        riskColor: riskColor,
                      ),

                      const SizedBox(height: 20),

                      Text(
                        'Today’s care plan',
                        style: TextStyle(
                          fontSize: 21,
                          fontWeight: FontWeight.w900,
                          color: AppColors.textDark,
                        ),
                      ),
                      const SizedBox(height: 12),

                      _CarePlanItem(
                        icon: Icons.monitor_heart_rounded,
                        color: AppColors.secondary,
                        title: 'Monitor health status',
                        subtitle: latest == null
                            ? 'No assessment found. Please complete one assessment.'
                            : 'Latest glucose: $glucose, BP: $bp',
                        status: latestRisk,
                      ),

                      _CarePlanItem(
                        icon: Icons.local_hospital_rounded,
                        color: riskColor,
                        title: 'Checkup recommendation',
                        subtitle:
                            latest?['recommendation']?.toString() ??
                            'No recommendation available yet.',
                        status: latestRisk == 'High'
                            ? 'Urgent'
                            : latestRisk == 'Medium'
                            ? 'Soon'
                            : 'Routine',
                      ),

                      if (alertMedicines.isNotEmpty)
                        ...alertMedicines.map((medicine) {
                          final remain = _remainingDays(
                            medicine['run_out_date'],
                          );
                          final name =
                              medicine['name']?.toString() ?? 'Medicine';

                          return _CarePlanItem(
                            icon: Icons.medication_rounded,
                            color: remain != null && remain <= 3
                                ? AppColors.danger
                                : AppColors.warning,
                            title: 'Medicine: $name',
                            subtitle: remain == null
                                ? 'Saved medicine record'
                                : remain <= 0
                                ? 'May already be finished'
                                : 'Estimated remaining: $remain day(s)',
                            status: remain == null
                                ? 'Saved'
                                : remain <= 3
                                ? 'Urgent'
                                : 'Active',
                          );
                        }),

                      if (alertMedicines.isEmpty)
                        _CarePlanItem(
                          icon: Icons.medication_rounded,
                          color: AppColors.success,
                          title: 'Medicine reminder',
                          subtitle: 'No urgent medicine restock alert found.',
                          status: 'Okay',
                        ),

                      const SizedBox(height: 20),

                      _MedicineAlertCard(
                        medicines: alertMedicines,
                        formatDate: _formatDate,
                        remainingDays: _remainingDays,
                      ),

                      const SizedBox(height: 20),

                      Text(
                        'Recent activity',
                        style: TextStyle(
                          fontSize: 21,
                          fontWeight: FontWeight.w900,
                          color: AppColors.textDark,
                        ),
                      ),
                      const SizedBox(height: 12),

                      _ActivityItem(
                        title: 'Total assessments',
                        subtitle:
                            '${assessments.length} assessment record(s) saved',
                        icon: Icons.analytics_rounded,
                        color: AppColors.secondary,
                      ),
                      _ActivityItem(
                        title: 'Total medicines',
                        subtitle:
                            '${medicines.length} medicine record(s) saved',
                        icon: Icons.medication_liquid_rounded,
                        color: AppColors.purple,
                      ),

                      const SizedBox(height: 20),

                      _EmergencyCard(contact: emergencyContact),
                    ],
                  ),
          ),
        ),
      ),
    );
  }
}

class _PatientHeader extends StatelessWidget {
  final String name;
  final String age;
  final String conditionSummary;

  const _PatientHeader({
    required this.name,
    required this.age,
    required this.conditionSummary,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        const CircleAvatar(
          radius: 34,
          backgroundColor: AppColors.mint,
          child: Icon(
            Icons.elderly_rounded,
            color: AppColors.primary,
            size: 38,
          ),
        ),
        const SizedBox(width: 16),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Hello, $name',
                style: TextStyle(
                  fontSize: 24,
                  fontWeight: FontWeight.w900,
                  color: AppColors.textDark,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                'Age $age • $conditionSummary',
                style: TextStyle(
                  color: AppColors.textSoft,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _HealthStatusCard extends StatelessWidget {
  final String latestRisk;
  final String diabetesRisk;
  final String heartRisk;
  final String glucose;
  final String bp;
  final Color riskColor;

  const _HealthStatusCard({
    required this.latestRisk,
    required this.diabetesRisk,
    required this.heartRisk,
    required this.glucose,
    required this.bp,
    required this.riskColor,
  });

  @override
  Widget build(BuildContext context) {
    return AppCard(
      padding: EdgeInsets.zero,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(24),
        decoration: BoxDecoration(
          color: AppColors.primaryDark,
          borderRadius: BorderRadius.circular(24),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(
              Icons.health_and_safety_rounded,
              color: Colors.white,
              size: 54,
            ),
            const SizedBox(height: 14),
            Text(
              'Current Health Status',
              style: TextStyle(
                color: Colors.white70,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 5),
            Text(
              latestRisk,
              style: TextStyle(
                color: Colors.white,
                fontSize: 30,
                fontWeight: FontWeight.w900,
              ),
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                _WhiteChip(label: 'Diabetes', value: diabetesRisk),
                _WhiteChip(label: 'Heart', value: heartRisk),
                _WhiteChip(label: 'Glucose', value: glucose),
                _WhiteChip(label: 'BP', value: bp),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _WhiteChip extends StatelessWidget {
  final String label;
  final String value;

  const _WhiteChip({required this.label, required this.value});

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
        style: TextStyle(
          color: Colors.white,
          fontWeight: FontWeight.w700,
          fontSize: 12,
        ),
      ),
    );
  }
}

class _CarePlanItem extends StatelessWidget {
  final IconData icon;
  final Color color;
  final String title;
  final String subtitle;
  final String status;

  const _CarePlanItem({
    required this.icon,
    required this.color,
    required this.title,
    required this.subtitle,
    required this.status,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: AppCard(
        child: Row(
          children: [
            CircleAvatar(
              backgroundColor: color.withValues(alpha: 0.12),
              child: Icon(icon, color: color),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: TextStyle(
                      fontWeight: FontWeight.w900,
                      color: AppColors.textDark,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    subtitle,
                    style: TextStyle(
                      color: AppColors.textSoft,
                      fontSize: 13,
                      height: 1.4,
                    ),
                  ),
                ],
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                color: color.withValues(alpha: 0.10),
                borderRadius: BorderRadius.circular(99),
              ),
              child: Text(
                status,
                style: TextStyle(
                  color: color,
                  fontSize: 11,
                  fontWeight: FontWeight.w900,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _MedicineAlertCard extends StatelessWidget {
  final List<Map<String, dynamic>> medicines;
  final String Function(dynamic) formatDate;
  final int? Function(dynamic) remainingDays;

  const _MedicineAlertCard({
    required this.medicines,
    required this.formatDate,
    required this.remainingDays,
  });

  @override
  Widget build(BuildContext context) {
    if (medicines.isEmpty) {
      return AppCard(
        child: Row(
          children: [
            const CircleAvatar(
              backgroundColor: AppColors.success,
              child: Icon(Icons.verified_rounded, color: Colors.white),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Text(
                'No urgent restock reminder found.',
                style: TextStyle(
                  fontWeight: FontWeight.w800,
                  color: AppColors.textDark,
                ),
              ),
            ),
          ],
        ),
      );
    }

    final first = medicines.first;
    final remain = remainingDays(first['run_out_date']);

    return AppCard(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const CircleAvatar(
            backgroundColor: AppColors.warning,
            child: Icon(
              Icons.notifications_active_rounded,
              color: Colors.white,
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Text(
              '${first['name']} run-out date: ${formatDate(first['run_out_date'])}. Remaining: ${remain ?? 'N/A'} day(s).',
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

class _ActivityItem extends StatelessWidget {
  final String title;
  final String subtitle;
  final IconData icon;
  final Color color;

  const _ActivityItem({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: AppCard(
        child: Row(
          children: [
            CircleAvatar(
              backgroundColor: color.withValues(alpha: 0.12),
              child: Icon(icon, color: color),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: TextStyle(
                      fontWeight: FontWeight.w900,
                      color: AppColors.textDark,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    subtitle,
                    style: TextStyle(color: AppColors.textSoft, fontSize: 13),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _EmergencyCard extends StatelessWidget {
  final String contact;

  const _EmergencyCard({required this.contact});

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Row(
        children: [
          const CircleAvatar(
            backgroundColor: AppColors.danger,
            child: Icon(Icons.emergency_rounded, color: Colors.white),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Text(
              'Emergency contact: $contact',
              style: TextStyle(
                fontWeight: FontWeight.w800,
                color: AppColors.textDark,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ErrorCard extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;

  const _ErrorCard({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return AppCard(
      padding: const EdgeInsets.all(24),
      child: Column(
        children: [
          const Icon(
            Icons.error_outline_rounded,
            size: 58,
            color: AppColors.danger,
          ),
          const SizedBox(height: 14),
          Text(
            message,
            textAlign: TextAlign.center,
            style: TextStyle(
              height: 1.5,
              color: AppColors.textDark,
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
    );
  }
}
