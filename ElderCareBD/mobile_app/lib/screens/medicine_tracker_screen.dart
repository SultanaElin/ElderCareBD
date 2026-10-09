import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../services/api_service.dart';
import '../services/session_service.dart';
import '../utils/app_colors.dart';
import '../widgets/app_card.dart';
import '../widgets/primary_button.dart';
import '../widgets/responsive_content.dart';

class MedicineTrackerScreen extends StatefulWidget {
  const MedicineTrackerScreen({super.key});

  @override
  State<MedicineTrackerScreen> createState() => _MedicineTrackerScreenState();
}

class _MedicineTrackerScreenState extends State<MedicineTrackerScreen> {
  final nameController = TextEditingController();
  final quantityController = TextEditingController();
  final dailyDoseController = TextEditingController();

  DateTime startDate = DateTime.now();

  bool isSaving = false;
  bool isLoading = true;
  String? errorMessage;

  List<dynamic> savedMedicines = [];

  @override
  void initState() {
    super.initState();
    _loadMedicines();
  }

  @override
  void dispose() {
    nameController.dispose();
    quantityController.dispose();
    dailyDoseController.dispose();
    super.dispose();
  }

  Future<void> _loadMedicines() async {
    setState(() {
      isLoading = true;
      errorMessage = null;
    });

    try {
      final patientId = await SessionService.getSelectedPatientId();

      if (patientId == null) {
        setState(() {
          savedMedicines = [];
          isLoading = false;
          errorMessage = 'Please save a patient profile first.';
        });
        return;
      }

      final medicines = await ApiService.getPatientMedicines(
        patientId: patientId,
      );

      setState(() {
        savedMedicines = medicines.reversed.toList();
        isLoading = false;
      });
    } catch (e) {
      setState(() {
        errorMessage = 'Failed to load medicines: $e';
        isLoading = false;
      });
    }
  }

  Future<void> _pickStartDate() async {
    final selected = await showDatePicker(
      context: context,
      initialDate: startDate,
      firstDate: DateTime(2020),
      lastDate: DateTime(2035),
    );

    if (selected == null) return;

    setState(() {
      startDate = selected;
    });
  }

  Future<void> _saveMedicine() async {
    final name = nameController.text.trim();
    final quantity = int.tryParse(quantityController.text.trim());
    final dailyDose = int.tryParse(dailyDoseController.text.trim());

    if (name.isEmpty ||
        quantity == null ||
        dailyDose == null ||
        dailyDose <= 0) {
      _showMessage(
        'Please enter medicine name, quantity, and valid daily dose.',
      );
      return;
    }

    final patientId = await SessionService.getSelectedPatientId();

    if (patientId == null) {
      _showMessage('Please save a patient profile first.');
      return;
    }

    final daysAvailable = (quantity / dailyDose).ceil();
    final runOutDate = startDate.add(Duration(days: daysAvailable));
    final alertDate = runOutDate.subtract(const Duration(days: 3));

    setState(() {
      isSaving = true;
    });

    try {
      final result = await ApiService.createMedicine(
        patientId: patientId,
        prescriptionId: null,
        name: name,
        dosage: null,
        frequency: null,
        quantity: quantity,
        dailyDose: dailyDose,
        startDate: DateFormat('yyyy-MM-dd').format(startDate),
        runOutDate: DateFormat('yyyy-MM-dd').format(runOutDate),
        alertDate: DateFormat('yyyy-MM-dd').format(alertDate),
        note: 'Medicine tracker entry',
      );

      if (!mounted) return;

      if (result['statusCode'] >= 200 && result['statusCode'] < 300) {
        _showMessage('Medicine tracking saved successfully.');

        nameController.clear();
        quantityController.clear();
        dailyDoseController.clear();

        setState(() {
          startDate = DateTime.now();
        });

        await _loadMedicines();
      } else {
        _showMessage('Could not save the medicine. Please try again.');
      }
    } catch (_) {
      if (mounted) {
        _showMessage(
          'Could not connect to the server. Check your connection and try again.',
        );
      }
    } finally {
      if (mounted) {
        setState(() {
          isSaving = false;
        });
      }
    }
  }

  void _showMessage(String message) {
    if (!mounted) return;

    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  String _formatDisplayDate(dynamic rawDate) {
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

  int? _remainingDays(dynamic rawRunOutDate) {
    if (rawRunOutDate == null || rawRunOutDate.toString().isEmpty) {
      return null;
    }

    try {
      final runOutDate = DateTime.parse(rawRunOutDate.toString());
      return runOutDate.difference(DateTime.now()).inDays;
    } catch (_) {
      return null;
    }
  }

  Color _statusColor(int? remainingDays) {
    if (remainingDays == null) return AppColors.info;
    if (remainingDays <= 3) return AppColors.danger;
    if (remainingDays <= 7) return AppColors.warning;
    return AppColors.success;
  }

  String _statusText(int? remainingDays) {
    if (remainingDays == null) return 'Saved medicine';
    if (remainingDays <= 0) return 'May be finished';
    if (remainingDays <= 3) return 'Urgent restock';
    if (remainingDays <= 7) return 'Restock soon';
    return 'Stock available';
  }

  @override
  Widget build(BuildContext context) {
    final dateFormat = DateFormat('dd MMM yyyy');

    return Scaffold(
      appBar: AppBar(
        title: const Text('Medicine Tracker'),
        actions: [
          IconButton(
            onPressed: _loadMedicines,
            tooltip: 'Refresh medicines',
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
      body: ResponsiveContent(
        maxWidth: 820,
        child: SingleChildScrollView(
          keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _IntroCard(),
              const SizedBox(height: 20),

              Text(
                'Add medicine stock',
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
                  labelText: 'Medicine name',
                  hintText: 'Example: Metformin',
                  prefixIcon: Icon(Icons.medication_rounded),
                ),
              ),
              const SizedBox(height: 14),

              AdaptiveFormRow(
                children: [
                  TextField(
                    controller: quantityController,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'Quantity',
                      hintText: '30',
                    ),
                  ),
                  TextField(
                    controller: dailyDoseController,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'Daily dose',
                      hintText: '2',
                    ),
                  ),
                ],
              ),

              const SizedBox(height: 14),

              AppCard(
                child: Row(
                  children: [
                    const Icon(
                      Icons.calendar_month_rounded,
                      color: AppColors.primary,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        'Start date: ${dateFormat.format(startDate)}',
                        style: TextStyle(
                          fontWeight: FontWeight.w700,
                          color: AppColors.textDark,
                        ),
                      ),
                    ),
                    TextButton(
                      onPressed: _pickStartDate,
                      child: const Text('Change'),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 18),

              if (isSaving)
                const Center(child: CircularProgressIndicator())
              else
                PrimaryButton(
                  text: 'Calculate & Save Medicine',
                  icon: Icons.calculate_rounded,
                  onPressed: _saveMedicine,
                ),

              const SizedBox(height: 26),

              Text(
                'Saved medicines',
                style: TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w900,
                  color: AppColors.primary,
                ),
              ),
              const SizedBox(height: 12),

              if (isLoading)
                const Center(
                  child: Padding(
                    padding: EdgeInsets.all(28),
                    child: CircularProgressIndicator(),
                  ),
                )
              else if (errorMessage != null)
                _ErrorCard(message: errorMessage!, onRetry: _loadMedicines)
              else if (savedMedicines.isEmpty)
                _EmptyMedicineCard(onRetry: _loadMedicines)
              else
                ...savedMedicines.map((item) {
                  final medicine = Map<String, dynamic>.from(item);
                  final remainingDays = _remainingDays(
                    medicine['run_out_date'],
                  );
                  final statusColor = _statusColor(remainingDays);

                  return _MedicineTrackingCard(
                    medicine: medicine,
                    remainingDays: remainingDays,
                    statusColor: statusColor,
                    statusText: _statusText(remainingDays),
                    startDate: _formatDisplayDate(medicine['start_date']),
                    runOutDate: _formatDisplayDate(medicine['run_out_date']),
                    alertDate: _formatDisplayDate(medicine['alert_date']),
                  );
                }),
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
            child: Icon(
              Icons.notifications_active_rounded,
              color: AppColors.primary,
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Text(
              'Enter medicine quantity and daily dose. The app calculates run-out date, creates a restock alert date, and saves the record to the backend database.',
              style: TextStyle(
                height: 1.55,
                fontWeight: FontWeight.w600,
                color: AppColors.textDark,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _MedicineTrackingCard extends StatelessWidget {
  final Map<String, dynamic> medicine;
  final int? remainingDays;
  final Color statusColor;
  final String statusText;
  final String startDate;
  final String runOutDate;
  final String alertDate;

  const _MedicineTrackingCard({
    required this.medicine,
    required this.remainingDays,
    required this.statusColor,
    required this.statusText,
    required this.startDate,
    required this.runOutDate,
    required this.alertDate,
  });

  @override
  Widget build(BuildContext context) {
    final name = medicine['name']?.toString() ?? 'Unknown medicine';
    final quantity = medicine['quantity']?.toString() ?? 'N/A';
    final dailyDose = medicine['daily_dose']?.toString() ?? 'N/A';
    final dosage = medicine['dosage']?.toString();
    final frequency = medicine['frequency']?.toString();

    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: AppCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                CircleAvatar(
                  backgroundColor: statusColor.withValues(alpha: 0.12),
                  child: Icon(Icons.medication_rounded, color: statusColor),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    name,
                    style: TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.w900,
                      color: AppColors.textDark,
                    ),
                  ),
                ),
                _StatusBadge(text: statusText, color: statusColor),
              ],
            ),

            const SizedBox(height: 12),

            if (dosage != null && dosage != 'null')
              _InfoRow(title: 'Dosage', value: dosage),
            if (frequency != null && frequency != 'null')
              _InfoRow(title: 'Frequency', value: frequency),

            _InfoRow(title: 'Quantity', value: quantity),
            _InfoRow(title: 'Daily dose', value: dailyDose),
            _InfoRow(title: 'Start date', value: startDate),
            _InfoRow(title: 'Run-out date', value: runOutDate),
            _InfoRow(title: 'Restock alert', value: alertDate),

            const SizedBox(height: 12),

            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: statusColor.withValues(alpha: 0.10),
                borderRadius: BorderRadius.circular(18),
              ),
              child: Text(
                remainingDays == null
                    ? 'This medicine was saved from prescription or tracker.'
                    : remainingDays! <= 0
                    ? 'This medicine may already be finished. Please review stock.'
                    : 'Estimated remaining days: $remainingDays day(s).',
                style: TextStyle(
                  fontWeight: FontWeight.w800,
                  color: statusColor,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatusBadge extends StatelessWidget {
  final String text;
  final Color color;

  const _StatusBadge({required this.text, required this.color});

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
          fontSize: 11,
          fontWeight: FontWeight.w900,
          color: color,
        ),
      ),
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
            width: 110,
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

class _EmptyMedicineCard extends StatelessWidget {
  final VoidCallback onRetry;

  const _EmptyMedicineCard({required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return AppCard(
      padding: const EdgeInsets.all(24),
      child: Column(
        children: [
          const Icon(
            Icons.medication_liquid_rounded,
            size: 58,
            color: AppColors.primary,
          ),
          const SizedBox(height: 14),
          Text(
            'No saved medicine found',
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w900,
              color: AppColors.textDark,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'Add medicine stock first. Saved medicines will appear here from the backend database.',
            textAlign: TextAlign.center,
            style: TextStyle(height: 1.5, color: AppColors.textSoft),
          ),
          const SizedBox(height: 16),
          OutlinedButton.icon(
            onPressed: onRetry,
            icon: const Icon(Icons.refresh_rounded),
            label: const Text('Refresh'),
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
