import 'package:flutter/material.dart';

import '../utils/app_colors.dart';
import '../widgets/app_card.dart';
import '../widgets/responsive_content.dart';

class MlResultsScreen extends StatelessWidget {
  const MlResultsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final results = [
      _ModelResult(
        disease: 'Diabetes Status Screening',
        dataset: 'DiaBD Bangladesh diabetes dataset',
        bestModel: 'Unweighted Logistic Regression (v3)',
        accuracy: '74.17%',
        f1: '27.42%',
        rocAuc: '81.98%',
        confusionMatrix: 'TN: 3664, FP: 1282, FN: 84, TP: 258',
        status:
            'Internal out-of-fold development diagnostic at the fixed 0.06 screening threshold; this is not external clinical validation.',
        color: AppColors.primary,
        icon: Icons.bloodtype_rounded,
      ),
      _ModelResult(
        disease: 'Heart Disease Screening',
        dataset: 'UCI Cleveland heart disease dataset',
        bestModel: 'Balanced Logistic Regression (v2)',
        accuracy: '77.44%',
        f1: '75.46%',
        rocAuc: '83.36%',
        confusionMatrix: 'TN: 127, FP: 33, FN: 34, TP: 103',
        status:
            'Internal out-of-fold development diagnostic at the fixed 0.53 screening threshold; this is not external clinical validation.',
        color: AppColors.danger,
        icon: Icons.favorite_rounded,
      ),
    ];

    return Scaffold(
      appBar: AppBar(title: const Text('ML Model Summary')),
      body: ResponsiveContent(
        maxWidth: 860,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _TopSummaryCard(),
              const SizedBox(height: 22),

              Text(
                'Validated research model summary',
                style: TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.w900,
                  color: AppColors.textDark,
                ),
              ),
              const SizedBox(height: 12),

              ...results.map((result) => _ModelResultCard(result: result)),

              const SizedBox(height: 22),

              _WorkflowCard(),

              const SizedBox(height: 22),

              _IntegrationStatusCard(),
            ],
          ),
        ),
      ),
    );
  }
}

class _TopSummaryCard extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return AppCard(
      padding: EdgeInsets.zero,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(24),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(24),
          color: AppColors.primaryDark,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.psychology_rounded, color: Colors.white, size: 58),
            const SizedBox(height: 14),
            Text(
              'Machine Learning Module',
              style: TextStyle(
                color: Colors.white,
                fontSize: 26,
                fontWeight: FontWeight.w900,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              'ElderCareBD uses verified server-side research/demo screening models when every model-compatible input is available. The existing rule-based heuristic remains a clearly labelled fallback.',
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.88),
                height: 1.55,
                fontWeight: FontWeight.w500,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ModelResultCard extends StatelessWidget {
  final _ModelResult result;

  const _ModelResultCard({required this.result});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: AppCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                CircleAvatar(
                  backgroundColor: result.color.withValues(alpha: 0.12),
                  child: Icon(result.icon, color: result.color),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        result.disease,
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w900,
                          color: AppColors.textDark,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        result.dataset,
                        style: TextStyle(
                          color: AppColors.textSoft,
                          fontSize: 12.5,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),

            const SizedBox(height: 16),

            _BestModelBadge(modelName: result.bestModel, color: result.color),

            const SizedBox(height: 16),

            Row(
              children: [
                Expanded(
                  child: _MetricBox(
                    title: 'OOF accuracy',
                    value: result.accuracy,
                    color: result.color,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _MetricBox(
                    title: 'OOF F1',
                    value: result.f1,
                    color: result.color,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _MetricBox(
                    title: 'OOF ROC-AUC',
                    value: result.rocAuc,
                    color: result.color,
                  ),
                ),
              ],
            ),

            const SizedBox(height: 16),

            _InfoBlock(
              title: 'Confusion matrix',
              value: result.confusionMatrix,
              icon: Icons.grid_on_rounded,
              color: result.color,
            ),

            const SizedBox(height: 12),

            _InfoBlock(
              title: 'Training note',
              value: result.status,
              icon: Icons.fact_check_rounded,
              color: AppColors.success,
            ),
          ],
        ),
      ),
    );
  }
}

class _BestModelBadge extends StatelessWidget {
  final String modelName;
  final Color color;

  const _BestModelBadge({required this.modelName, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(18),
      ),
      child: Row(
        children: [
          Icon(Icons.emoji_events_rounded, color: color),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              'Best Model: $modelName',
              style: TextStyle(color: color, fontWeight: FontWeight.w900),
            ),
          ),
        ],
      ),
    );
  }
}

class _MetricBox extends StatelessWidget {
  final String title;
  final String value;
  final Color color;

  const _MetricBox({
    required this.title,
    required this.value,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 8),
      decoration: BoxDecoration(
        color: AppColors.mint,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        children: [
          Text(
            value,
            style: TextStyle(
              color: color,
              fontSize: 17,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            title,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: AppColors.textSoft,
              fontSize: 11.5,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

class _InfoBlock extends StatelessWidget {
  final String title;
  final String value;
  final IconData icon;
  final Color color;

  const _InfoBlock({
    required this.title,
    required this.value,
    required this.icon,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(18),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 22),
          const SizedBox(width: 10),
          Expanded(
            child: RichText(
              text: TextSpan(
                style: TextStyle(color: AppColors.textDark, height: 1.45),
                children: [
                  TextSpan(
                    text: '$title: ',
                    style: const TextStyle(fontWeight: FontWeight.w900),
                  ),
                  TextSpan(text: value),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _WorkflowCard extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final steps = [
      'Dataset loading',
      'Preprocessing',
      'Model training',
      '5-fold stratified cross-validation',
      'Metric comparison',
      'Best model selection',
      'Model saving as .pkl',
    ];

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'ML workflow completed',
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w900,
              color: AppColors.textDark,
            ),
          ),
          const SizedBox(height: 14),
          ...steps.map(
            (step) => Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Row(
                children: [
                  const Icon(
                    Icons.check_circle_rounded,
                    color: AppColors.success,
                    size: 21,
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      step,
                      style: TextStyle(
                        color: AppColors.textDark,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _IntegrationStatusCard extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return AppCard(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const CircleAvatar(
            backgroundColor: AppColors.success,
            child: Icon(Icons.check_circle_rounded, color: Colors.white),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Text(
              'Integration active: authenticated assessments compute DiaBD v3 and Heart v2 screening scores on the server when exact inputs are compatible. Scores are not diagnoses or clinically validated personal probabilities; fallback results remain explicitly labelled.',
              style: TextStyle(
                color: AppColors.textDark,
                height: 1.55,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ModelResult {
  final String disease;
  final String dataset;
  final String bestModel;
  final String accuracy;
  final String f1;
  final String rocAuc;
  final String confusionMatrix;
  final String status;
  final Color color;
  final IconData icon;

  _ModelResult({
    required this.disease,
    required this.dataset,
    required this.bestModel,
    required this.accuracy,
    required this.f1,
    required this.rocAuc,
    required this.confusionMatrix,
    required this.status,
    required this.color,
    required this.icon,
  });
}
