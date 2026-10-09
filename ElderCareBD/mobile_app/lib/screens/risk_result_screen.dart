import 'package:flutter/material.dart';

import '../models/model_prediction.dart';
import '../utils/app_colors.dart';
import '../widgets/app_card.dart';
import '../widgets/primary_button.dart';
import '../widgets/responsive_content.dart';

class RiskResultScreen extends StatelessWidget {
  final String diabetesRisk;
  final String heartRisk;
  final String overallRisk;
  final String recommendation;
  final AssessmentPredictions? predictions;

  const RiskResultScreen({
    super.key,
    required this.diabetesRisk,
    required this.heartRisk,
    required this.overallRisk,
    required this.recommendation,
    this.predictions,
  });

  Color _riskColor(String risk) {
    if (risk == 'High') return AppColors.danger;
    if (risk == 'Medium') return AppColors.warning;
    if (risk == 'Low') return AppColors.success;
    return AppColors.primary;
  }

  @override
  Widget build(BuildContext context) {
    final overallColor = _riskColor(overallRisk);

    return Scaffold(
      appBar: AppBar(title: const Text('Risk Result')),
      body: ResponsiveContent(
        maxWidth: 760,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              AppCard(
                padding: EdgeInsets.zero,
                child: Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(26),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(24),
                    color: AppColors.primaryDark,
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Icon(
                        Icons.health_and_safety_rounded,
                        color: Colors.white,
                        size: 60,
                      ),
                      const SizedBox(height: 16),
                      Text(
                        'General heuristic screening',
                        style: TextStyle(
                          color: Colors.white70,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        overallRisk,
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 38,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      const SizedBox(height: 10),
                      Text(
                        'Combined demo heuristic based on the general vitals, BMI, and symptoms. Disease-model results are identified separately below.',
                        style: TextStyle(
                          color: Colors.white.withValues(alpha: 0.88),
                          height: 1.5,
                        ),
                      ),
                    ],
                  ),
                ),
              ),

              const SizedBox(height: 22),

              Text(
                'Disease-specific risk',
                style: TextStyle(
                  fontSize: 21,
                  fontWeight: FontWeight.w900,
                  color: AppColors.textDark,
                ),
              ),

              const SizedBox(height: 12),

              _RiskCard(
                title: 'Diabetes status screening',
                heuristicRisk: diabetesRisk,
                modelPrediction: predictions?.diabetes,
                icon: Icons.bloodtype_rounded,
                heuristicColor: _riskColor(diabetesRisk),
              ),

              const SizedBox(height: 12),

              _RiskCard(
                title: 'Heart-disease screening',
                heuristicRisk: heartRisk,
                modelPrediction: predictions?.heart,
                icon: Icons.favorite_rounded,
                heuristicColor: _riskColor(heartRisk),
              ),

              const SizedBox(height: 22),

              Text(
                'General heuristic recommendation',
                style: TextStyle(
                  fontSize: 21,
                  fontWeight: FontWeight.w900,
                  color: AppColors.textDark,
                ),
              ),

              const SizedBox(height: 12),

              AppCard(
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    CircleAvatar(
                      backgroundColor: overallColor.withValues(alpha: 0.12),
                      child: Icon(
                        Icons.medical_services_rounded,
                        color: overallColor,
                      ),
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Text(
                        recommendation,
                        style: TextStyle(
                          color: AppColors.textDark,
                          height: 1.55,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 18),

              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: AppColors.warning.withValues(alpha: 0.10),
                  borderRadius: BorderRadius.circular(18),
                  border: Border.all(
                    color: AppColors.warning.withValues(alpha: 0.35),
                  ),
                ),
                child: Text(
                  'Note: This result is for preliminary screening support only and is not a replacement for professional medical diagnosis.',
                  style: TextStyle(
                    color: AppColors.textDark,
                    height: 1.45,
                    fontWeight: FontWeight.w600,
                    fontSize: 12.8,
                  ),
                ),
              ),

              const SizedBox(height: 24),

              PrimaryButton(
                text: 'Back to Dashboard',
                icon: Icons.dashboard_rounded,
                onPressed: () {
                  Navigator.pop(context);
                  Navigator.pop(context);
                },
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _RiskCard extends StatelessWidget {
  final String title;
  final String heuristicRisk;
  final DiseasePrediction? modelPrediction;
  final IconData icon;
  final Color heuristicColor;

  const _RiskCard({
    required this.title,
    required this.heuristicRisk,
    required this.modelPrediction,
    required this.icon,
    required this.heuristicColor,
  });

  @override
  Widget build(BuildContext context) {
    final prediction = modelPrediction;
    final usesModel = prediction?.isModelPrediction == true;
    final knownDiabetes =
        prediction?.predictionStatus == 'not_applicable_known_diabetes';
    final color = usesModel || knownDiabetes
        ? AppColors.primary
        : heuristicColor;

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              CircleAvatar(
                backgroundColor: color.withValues(alpha: 0.12),
                child: Icon(icon, color: color),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Text(
                  title,
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w900,
                    color: AppColors.textDark,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          if (knownDiabetes) ...[
            Text(
              'Screening not applicable',
              style: TextStyle(
                color: AppColors.primary,
                fontSize: 17,
                fontWeight: FontWeight.w900,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              prediction!.fallbackMessage,
              style: TextStyle(
                color: AppColors.textSoft,
                height: 1.4,
                fontSize: 12.5,
              ),
            ),
          ] else if (usesModel && prediction!.disease == 'heart') ...[
            HeartScreeningModelResult(prediction: prediction),
          ] else if (usesModel) ...[
            Text(
              '${prediction!.modelDisplayLabel} - version ${prediction.modelVersion}',
              style: TextStyle(
                color: AppColors.textSoft,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              'Screening-model score: ${prediction.riskScore!.toStringAsFixed(2)}',
              style: TextStyle(
                color: color,
                fontSize: 18,
                fontWeight: FontWeight.w900,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              prediction.classificationLabel,
              style: TextStyle(
                color: AppColors.textDark,
                fontWeight: FontWeight.w800,
              ),
            ),
            Text(
              'Screening-model threshold: ${prediction.threshold!.toStringAsFixed(2)}',
              style: TextStyle(color: AppColors.textSoft),
            ),
            const SizedBox(height: 8),
            Text(
              prediction.disclaimer,
              style: TextStyle(
                color: AppColors.textSoft,
                height: 1.4,
                fontSize: 12.5,
              ),
            ),
          ] else ...[
            Text(
              'Heuristic demo fallback',
              style: TextStyle(
                color: AppColors.textSoft,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 6),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
              decoration: BoxDecoration(
                color: color.withValues(alpha: 0.10),
                borderRadius: BorderRadius.circular(99),
              ),
              child: Text(
                heuristicRisk,
                style: TextStyle(
                  color: color,
                  fontSize: 13,
                  fontWeight: FontWeight.w900,
                ),
              ),
            ),
            const SizedBox(height: 8),
            Text(
              prediction?.fallbackMessage ??
                  'No model-compatible result was stored for this assessment.',
              style: TextStyle(
                color: AppColors.textSoft,
                height: 1.4,
                fontSize: 12.5,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class HeartScreeningModelResult extends StatelessWidget {
  const HeartScreeningModelResult({super.key, required this.prediction});

  final DiseasePrediction prediction;

  @override
  Widget build(BuildContext context) {
    final score = prediction.riskScore!;
    final threshold = prediction.threshold!;
    final requiresAttention = score >= threshold;
    final accent = requiresAttention ? AppColors.warning : AppColors.primary;
    final heading = requiresAttention
        ? 'Screening result requires attention'
        : 'Below screening threshold';
    final explanation = requiresAttention
        ? 'The current inputs were flagged at or above the screening threshold. Consider discussing the result with a healthcare professional.'
        : 'The current inputs were not flagged by the heart screening model.';
    final disclaimer = requiresAttention
        ? 'This result does not confirm heart disease.'
        : 'This is a screening result, not a diagnosis.';

    return Column(
      key: const Key('heart-screening-model-result'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              requiresAttention
                  ? Icons.priority_high_rounded
                  : Icons.check_circle_outline_rounded,
              color: accent,
              semanticLabel: heading,
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                heading,
                key: const Key('heart-screening-heading'),
                style: TextStyle(
                  color: AppColors.textDark,
                  fontSize: 18,
                  fontWeight: FontWeight.w900,
                  height: 1.3,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Text(
          explanation,
          key: const Key('heart-screening-explanation'),
          style: const TextStyle(color: AppColors.textDark, height: 1.5),
        ),
        const SizedBox(height: 8),
        Text(
          disclaimer,
          key: const Key('heart-screening-disclaimer'),
          style: const TextStyle(
            color: AppColors.textSoft,
            height: 1.45,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 8),
        Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            key: const Key('heart-technical-details'),
            tilePadding: EdgeInsets.zero,
            childrenPadding: const EdgeInsets.only(bottom: 8),
            title: const Text(
              'Technical details',
              style: TextStyle(
                color: AppColors.primary,
                fontWeight: FontWeight.w800,
              ),
            ),
            children: [
              Align(
                alignment: Alignment.centerLeft,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Model: Heart v2'),
                    const SizedBox(height: 4),
                    Text('Model score: ${score.toStringAsFixed(2)}'),
                    const SizedBox(height: 4),
                    Text(
                      'Screening threshold: ${threshold.toStringAsFixed(2)}',
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
