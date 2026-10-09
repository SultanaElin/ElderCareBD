import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../models/daily_observation.dart';
import '../services/api_service.dart';
import '../services/session_service.dart';
import '../utils/app_colors.dart';
import '../utils/app_spacing.dart';
import '../widgets/app_card.dart';
import '../widgets/responsive_content.dart';
import '../widgets/section_header.dart';

typedef ObservationListLoader =
    Future<List<DailyObservation>> Function(int patientId);
typedef TrendsPatientIdLoader = Future<int?> Function();
typedef TrendsPatientNameLoader = Future<String?> Function();

enum HealthTrendMetric {
  systolic,
  diastolic,
  spo2,
  pulse,
  weight,
  temperature,
  glucose,
}

class HealthTrendPoint {
  const HealthTrendPoint({required this.date, required this.value});

  final DateTime date;
  final double value;
}

List<DailyObservation> filterLastSevenCalendarDays(
  Iterable<DailyObservation> observations,
  DateTime referenceDate,
) {
  final today = DateTime.utc(
    referenceDate.year,
    referenceDate.month,
    referenceDate.day,
  );
  final firstDay = today.subtract(const Duration(days: 6));
  final filtered = observations.where((observation) {
    final date = DateTime.utc(
      observation.observationDate.year,
      observation.observationDate.month,
      observation.observationDate.day,
    );
    return !date.isBefore(firstDay) && !date.isAfter(today);
  }).toList();
  filtered.sort((left, right) {
    final dateOrder = left.observationDate.compareTo(right.observationDate);
    return dateOrder != 0 ? dateOrder : left.id.compareTo(right.id);
  });
  return filtered;
}

class HealthTrendsScreen extends StatefulWidget {
  const HealthTrendsScreen({
    super.key,
    this.observationLoader,
    this.patientIdLoader,
    this.patientNameLoader,
    this.referenceDate,
  });

  final ObservationListLoader? observationLoader;
  final TrendsPatientIdLoader? patientIdLoader;
  final TrendsPatientNameLoader? patientNameLoader;
  final DateTime? referenceDate;

  @override
  State<HealthTrendsScreen> createState() => _HealthTrendsScreenState();
}

class _HealthTrendsScreenState extends State<HealthTrendsScreen> {
  bool _loading = true;
  String? _error;
  String _patientName = 'Selected patient';
  List<DailyObservation> _observations = const [];
  HealthTrendMetric _metric = HealthTrendMetric.systolic;
  String? _selectedUnit;

  DateTime get _today => widget.referenceDate ?? DateTime.now().toUtc();

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
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
          _loading = false;
          _error =
              'Select a patient from the caregiver dashboard before viewing trends.';
        });
        return;
      }

      final loader =
          widget.observationLoader ??
          (id) => ApiService.getPatientObservations(patientId: id);
      final observations = await loader(patientId);
      if (!mounted) return;
      setState(() {
        _patientName = patientName?.trim().isNotEmpty == true
            ? patientName!.trim()
            : 'Selected patient';
        _observations = filterLastSevenCalendarDays(observations, _today);
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = switch (error.statusCode) {
          401 => 'Your session has expired. Please sign in again.',
          404 =>
            'This patient is unavailable or no longer belongs to your account.',
          _ => error.message,
        };
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Could not load recent health observations. Please try again.';
      });
    }
  }

  _MetricInfo get _metricInfo => _MetricInfo.forMetric(_metric);

  List<String> _availableUnits() {
    final allowed = switch (_metric) {
      HealthTrendMetric.temperature => const ['C', 'F'],
      HealthTrendMetric.glucose => const ['mg/dL', 'mmol/L'],
      _ => <String>[],
    };
    if (allowed.isEmpty) return allowed;
    return allowed.where((unit) {
      return _observations.any((observation) {
        return switch (_metric) {
          HealthTrendMetric.temperature =>
            observation.values.temperatureValue != null &&
                observation.values.temperatureUnit == unit,
          HealthTrendMetric.glucose =>
            observation.values.glucoseValue != null &&
                observation.values.glucoseUnit == unit,
          _ => false,
        };
      });
    }).toList();
  }

  String? get _effectiveUnit {
    final fixedUnit = _metricInfo.fixedUnit;
    if (fixedUnit != null) return fixedUnit;
    final available = _availableUnits();
    if (available.contains(_selectedUnit)) return _selectedUnit;
    return available.firstOrNull;
  }

  List<HealthTrendPoint> _points() {
    final unit = _effectiveUnit;
    return [
      for (final observation in _observations)
        if (_metricInfo.valueOf(observation, unit) case final value?)
          HealthTrendPoint(date: observation.observationDate, value: value),
    ];
  }

  void _selectMetric(HealthTrendMetric metric) {
    setState(() {
      _metric = metric;
      _selectedUnit = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final largeText = MediaQuery.textScalerOf(context).scale(1) >= 1.5;
    return Scaffold(
      appBar: AppBar(
        title: Text(largeText ? 'Health Trends' : '7-Day Health Trends'),
      ),
      body: ResponsiveContent(
        maxWidth: AppSpacing.formMaxWidth,
        padding: const EdgeInsets.all(AppSpacing.md),
        fillHeight: true,
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : RefreshIndicator(
                onRefresh: _load,
                child: SingleChildScrollView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  child: _buildContent(context),
                ),
              ),
      ),
    );
  }

  Widget _buildContent(BuildContext context) {
    if (_error != null) {
      return _MessageCard(
        icon: Icons.error_outline_rounded,
        message: _error!,
        actionLabel: 'Try again',
        onAction: _load,
      );
    }
    if (_observations.isEmpty) {
      return const _MessageCard(
        icon: Icons.calendar_today_outlined,
        message: 'No observations recorded in the last 7 days.',
      );
    }

    final info = _metricInfo;
    final unit = _effectiveUnit;
    final points = _points();
    final unitOptions = _availableUnits();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        AppCard(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const CircleAvatar(
                backgroundColor: AppColors.mint,
                child: Icon(Icons.show_chart_rounded, color: AppColors.primary),
              ),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _patientName,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: AppColors.textDark,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    const SizedBox(height: 4),
                    const Text(
                      'Stored measurements from the last 7 calendar days.',
                      style: TextStyle(color: AppColors.textSoft, height: 1.4),
                    ),
                  ],
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
                title: 'Choose a measurement',
                subtitle: 'One measurement is displayed at a time.',
              ),
              const SizedBox(height: AppSpacing.sm),
              Wrap(
                spacing: AppSpacing.xs,
                runSpacing: AppSpacing.xs,
                children: [
                  for (final metric in HealthTrendMetric.values)
                    ChoiceChip(
                      key: Key('trend-metric-${metric.name}'),
                      label: Text(_MetricInfo.forMetric(metric).chipLabel),
                      selected: _metric == metric,
                      onSelected: (_) => _selectMetric(metric),
                    ),
                ],
              ),
              if (unitOptions.length > 1) ...[
                const SizedBox(height: AppSpacing.md),
                Text(
                  'Stored unit',
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    color: AppColors.textDark,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: AppSpacing.xs),
                Wrap(
                  spacing: AppSpacing.xs,
                  runSpacing: AppSpacing.xs,
                  children: [
                    for (final option in unitOptions)
                      ChoiceChip(
                        key: Key('trend-unit-$option'),
                        label: Text(option),
                        selected: unit == option,
                        onSelected: (_) =>
                            setState(() => _selectedUnit = option),
                      ),
                  ],
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SectionHeader(
                title: info.title,
                subtitle: unit == null ? 'No explicit unit available' : 'Unit: $unit',
              ),
              const SizedBox(height: AppSpacing.md),
              if (points.isEmpty)
                _MissingMetricMessage(metricName: info.title)
              else ...[
                Text(
                  points.length == 1
                      ? 'One measurement is available for this metric in the selected period.'
                      : '${points.length} measurements are available across the last 7 days.',
                  key: const Key('trend-sparse-message'),
                  style: const TextStyle(
                    color: AppColors.textSoft,
                    height: 1.4,
                  ),
                ),
                const SizedBox(height: AppSpacing.sm),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final width = math.max(560.0, constraints.maxWidth);
                    return SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: SizedBox(
                        width: width,
                        child: HealthTrendChart(
                          key: const Key('trend-chart'),
                          points: points,
                          firstDate: _sevenDayStart(_today),
                          unit: unit!,
                        ),
                      ),
                    );
                  },
                ),
                const SizedBox(height: AppSpacing.md),
                Text(
                  'Recorded values',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    color: AppColors.textDark,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: AppSpacing.xs),
                for (final point in points)
                  _RecordedValueRow(point: point, unit: unit!),
              ],
              if ((_metric == HealthTrendMetric.temperature ||
                      _metric == HealthTrendMetric.glucose) &&
                  _hasUnitlessValues()) ...[
                const SizedBox(height: AppSpacing.sm),
                const Text(
                  'Measurements without an explicit stored unit are not displayed.',
                  style: TextStyle(color: AppColors.textSoft, height: 1.4),
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        const Text(
          'This screen displays stored measurements only and does not provide clinical interpretation.',
          style: TextStyle(color: AppColors.textSoft, height: 1.4),
        ),
        const SizedBox(height: AppSpacing.md),
      ],
    );
  }

  bool _hasUnitlessValues() {
    return _observations.any((observation) {
      return switch (_metric) {
        HealthTrendMetric.temperature =>
          observation.values.temperatureValue != null &&
              observation.values.temperatureUnit == null,
        HealthTrendMetric.glucose =>
          observation.values.glucoseValue != null &&
              observation.values.glucoseUnit == null,
        _ => false,
      };
    });
  }
}

class _MetricInfo {
  const _MetricInfo({
    required this.chipLabel,
    required this.title,
    required this.fixedUnit,
    required this.valueOf,
  });

  final String chipLabel;
  final String title;
  final String? fixedUnit;
  final double? Function(DailyObservation observation, String? unit) valueOf;

  static _MetricInfo forMetric(HealthTrendMetric metric) {
    return switch (metric) {
      HealthTrendMetric.systolic => _MetricInfo(
        chipLabel: 'Systolic BP',
        title: 'Systolic blood pressure',
        fixedUnit: 'mmHg',
        valueOf: (observation, _) => observation.values.systolicBp,
      ),
      HealthTrendMetric.diastolic => _MetricInfo(
        chipLabel: 'Diastolic BP',
        title: 'Diastolic blood pressure',
        fixedUnit: 'mmHg',
        valueOf: (observation, _) => observation.values.diastolicBp,
      ),
      HealthTrendMetric.spo2 => _MetricInfo(
        chipLabel: 'SpO₂',
        title: 'SpO₂',
        fixedUnit: '%',
        valueOf: (observation, _) => observation.values.spo2Percent,
      ),
      HealthTrendMetric.pulse => _MetricInfo(
        chipLabel: 'Pulse',
        title: 'Pulse',
        fixedUnit: 'bpm',
        valueOf: (observation, _) => observation.values.pulseBpm,
      ),
      HealthTrendMetric.weight => _MetricInfo(
        chipLabel: 'Weight',
        title: 'Weight',
        fixedUnit: 'kg',
        valueOf: (observation, _) => observation.values.weightKg,
      ),
      HealthTrendMetric.temperature => _MetricInfo(
        chipLabel: 'Temperature',
        title: 'Temperature',
        fixedUnit: null,
        valueOf: (observation, unit) =>
            observation.values.temperatureUnit == unit
            ? observation.values.temperatureValue
            : null,
      ),
      HealthTrendMetric.glucose => _MetricInfo(
        chipLabel: 'Glucose',
        title: 'Glucose',
        fixedUnit: null,
        valueOf: (observation, unit) => observation.values.glucoseUnit == unit
            ? observation.values.glucoseValue
            : null,
      ),
    };
  }
}

class HealthTrendChart extends StatelessWidget {
  const HealthTrendChart({
    super.key,
    required this.points,
    required this.firstDate,
    required this.unit,
  });

  final List<HealthTrendPoint> points;
  final DateTime firstDate;
  final String unit;

  @override
  Widget build(BuildContext context) {
    final summary = points
        .map(
          (point) =>
              '${DateFormat('d MMM').format(point.date)} ${_formatValue(point.value)} $unit',
        )
        .join(', ');
    return Semantics(
      label: 'Seven-day measurement chart. $summary',
      child: SizedBox(
        height: 260,
        child: CustomPaint(
          painter: _HealthTrendPainter(
            points: points,
            firstDate: firstDate,
            textDirection: Directionality.of(context),
          ),
        ),
      ),
    );
  }
}

class _HealthTrendPainter extends CustomPainter {
  const _HealthTrendPainter({
    required this.points,
    required this.firstDate,
    required this.textDirection,
  });

  final List<HealthTrendPoint> points;
  final DateTime firstDate;
  final TextDirection textDirection;

  @override
  void paint(Canvas canvas, Size size) {
    const left = 52.0;
    const right = 14.0;
    const top = 22.0;
    const bottom = 48.0;
    final chartWidth = size.width - left - right;
    final chartHeight = size.height - top - bottom;
    final axis = Paint()
      ..color = AppColors.border
      ..strokeWidth = 1;
    final grid = Paint()
      ..color = AppColors.border.withValues(alpha: 0.65)
      ..strokeWidth = 1;
    final line = Paint()
      ..color = AppColors.primary
      ..strokeWidth = 3
      ..strokeCap = StrokeCap.round;
    final pointPaint = Paint()..color = AppColors.primaryDark;

    canvas.drawLine(
      const Offset(left, top),
      Offset(left, top + chartHeight),
      axis,
    );
    canvas.drawLine(
      Offset(left, top + chartHeight),
      Offset(left + chartWidth, top + chartHeight),
      axis,
    );
    for (var row = 0; row <= 2; row++) {
      final y = top + (chartHeight * row / 2);
      canvas.drawLine(Offset(left, y), Offset(left + chartWidth, y), grid);
    }

    final values = points.map((point) => point.value).toList();
    final minimum = values.reduce(math.min);
    final maximum = values.reduce(math.max);
    final span = maximum - minimum;

    Offset offsetFor(HealthTrendPoint point) {
      final pointDate = DateTime.utc(
        point.date.year,
        point.date.month,
        point.date.day,
      );
      final start = DateTime.utc(
        firstDate.year,
        firstDate.month,
        firstDate.day,
      );
      final day = pointDate.difference(start).inDays.clamp(0, 6);
      final x = left + (chartWidth * day / 6);
      final normalized = span == 0 ? 0.5 : (point.value - minimum) / span;
      final y = top + chartHeight - (normalized * chartHeight);
      return Offset(x, y);
    }

    for (var index = 1; index < points.length; index++) {
      final previousDate = DateTime.utc(
        points[index - 1].date.year,
        points[index - 1].date.month,
        points[index - 1].date.day,
      );
      final currentDate = DateTime.utc(
        points[index].date.year,
        points[index].date.month,
        points[index].date.day,
      );
      if (currentDate.difference(previousDate).inDays == 1) {
        canvas.drawLine(
          offsetFor(points[index - 1]),
          offsetFor(points[index]),
          line,
        );
      }
    }
    for (final point in points) {
      canvas.drawCircle(offsetFor(point), 5.5, pointPaint);
      canvas.drawCircle(offsetFor(point), 2.5, Paint()..color = Colors.white);
    }

    _drawLabel(canvas, _formatValue(maximum), const Offset(0, top - 8));
    _drawLabel(
      canvas,
      _formatValue(minimum),
      Offset(0, top + chartHeight - 8),
    );
    for (var day = 0; day < 7; day++) {
      final date = firstDate.add(Duration(days: day));
      final x = left + (chartWidth * day / 6);
      _drawCenteredLabel(
        canvas,
        DateFormat('d MMM').format(date),
        Offset(x, top + chartHeight + 14),
      );
    }
  }

  void _drawLabel(Canvas canvas, String value, Offset offset) {
    final painter = TextPainter(
      text: const TextSpan(
        style: TextStyle(color: AppColors.textSoft, fontSize: 11),
      ),
      textDirection: textDirection,
    )..text = TextSpan(
      text: value,
      style: const TextStyle(color: AppColors.textSoft, fontSize: 11),
    );
    painter.layout(maxWidth: 46);
    painter.paint(canvas, offset);
  }

  void _drawCenteredLabel(Canvas canvas, String value, Offset center) {
    final painter = TextPainter(
      text: TextSpan(
        text: value,
        style: const TextStyle(color: AppColors.textSoft, fontSize: 11),
      ),
      textDirection: textDirection,
    )..layout();
    painter.paint(canvas, Offset(center.dx - painter.width / 2, center.dy));
  }

  @override
  bool shouldRepaint(covariant _HealthTrendPainter oldDelegate) {
    return oldDelegate.points != points || oldDelegate.firstDate != firstDate;
  }
}

class _RecordedValueRow extends StatelessWidget {
  const _RecordedValueRow({required this.point, required this.unit});

  final HealthTrendPoint point;
  final String unit;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
      child: Row(
        children: [
          Expanded(
            child: Text(
              DateFormat('EEE, d MMM').format(point.date),
              style: const TextStyle(color: AppColors.textSoft),
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          Text(
            '${_formatValue(point.value)} $unit',
            key: Key(
              'trend-value-${point.date.year}-${point.date.month}-${point.date.day}',
            ),
            style: const TextStyle(
              color: AppColors.textDark,
              fontWeight: FontWeight.w900,
            ),
          ),
        ],
      ),
    );
  }
}

class _MissingMetricMessage extends StatelessWidget {
  const _MissingMetricMessage({required this.metricName});

  final String metricName;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('trend-metric-empty'),
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.lightYellow.withValues(alpha: 0.55),
        borderRadius: BorderRadius.circular(AppSpacing.inputRadius),
      ),
      child: Text(
        'No $metricName measurements recorded in the last 7 days.',
        style: const TextStyle(color: AppColors.textDark, height: 1.4),
      ),
    );
  }
}

class _MessageCard extends StatelessWidget {
  const _MessageCard({
    required this.icon,
    required this.message,
    this.actionLabel,
    this.onAction,
  });

  final IconData icon;
  final String message;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 44, color: AppColors.primary),
          const SizedBox(height: AppSpacing.sm),
          Text(
            message,
            textAlign: TextAlign.center,
            style: const TextStyle(color: AppColors.textDark, height: 1.4),
          ),
          if (actionLabel != null && onAction != null) ...[
            const SizedBox(height: AppSpacing.md),
            SizedBox(
              height: AppSpacing.minimumTouchTarget,
              child: OutlinedButton(
                onPressed: onAction,
                child: Text(actionLabel!),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

DateTime _sevenDayStart(DateTime referenceDate) {
  return DateTime.utc(
    referenceDate.year,
    referenceDate.month,
    referenceDate.day,
  ).subtract(const Duration(days: 6));
}

String _formatValue(double value) {
  return value == value.roundToDouble()
      ? value.toInt().toString()
      : value.toStringAsFixed(1).replaceFirst(RegExp(r'\.0$'), '');
}
