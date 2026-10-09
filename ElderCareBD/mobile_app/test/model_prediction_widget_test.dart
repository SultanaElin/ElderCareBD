import 'dart:convert';

import 'package:eldercare_bd/models/model_prediction.dart';
import 'package:eldercare_bd/screens/history_screen.dart';
import 'package:eldercare_bd/screens/ml_results_screen.dart';
import 'package:eldercare_bd/screens/risk_result_screen.dart';
import 'package:eldercare_bd/widgets/app_card.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  testWidgets('result displays model score and threshold classification only', (
    tester,
  ) async {
    final model = DiseasePrediction(
      disease: 'diabetes',
      predictionSource: 'task13b_diabd_v3_model',
      predictionStatus: 'predicted',
      modelVersion: '3.0.0',
      riskScore: 0.64,
      classification: 'at_or_above_model_threshold',
      threshold: 0.06,
      disclaimer: 'Non-diagnostic research screening only.',
    );

    await tester.pumpWidget(
      MaterialApp(
        home: RiskResultScreen(
          diabetesRisk: 'Medium',
          heartRisk: 'Low',
          overallRisk: 'Medium',
          recommendation: 'Demo recommendation.',
          predictions: AssessmentPredictions(
            diabetes: model,
            heart: DiseasePrediction.fallback(
              disease: 'heart',
              predictionStatus: 'skipped_missing_model_input',
              message: 'Exact heart inputs were not provided.',
            ),
          ),
        ),
      ),
    );

    expect(find.text('Screening-model score: 0.64'), findsOneWidget);
    expect(find.text('At/above screening-model threshold'), findsOneWidget);
    expect(find.text('Screening-model threshold: 0.06'), findsOneWidget);
    expect(find.text('Heuristic demo fallback'), findsOneWidget);
    expect(
      find.descendant(
        of: find.widgetWithText(AppCard, 'Diabetes status screening'),
        matching: find.text('Medium'),
      ),
      findsNothing,
    );
  });

  testWidgets('known diabetes displays bypass without a fabricated score', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: RiskResultScreen(
          diabetesRisk: 'High',
          heartRisk: 'Low',
          overallRisk: 'High',
          recommendation: 'Demo recommendation.',
          predictions: AssessmentPredictions(
            diabetes: DiseasePrediction.fallback(
              disease: 'diabetes',
              predictionSource: 'known_condition',
              predictionStatus: 'not_applicable_known_diabetes',
              message:
                  'Diabetes screening was not run because diabetes is already recorded for this patient.',
            ),
            heart: DiseasePrediction.fallback(
              disease: 'heart',
              predictionStatus: 'skipped_missing_model_input',
              message: 'Exact heart inputs were not provided.',
            ),
          ),
        ),
      ),
    );

    expect(find.text('Screening not applicable'), findsOneWidget);
    expect(find.textContaining('already recorded'), findsOneWidget);
    expect(find.textContaining('Screening-model score'), findsNothing);
  });

  testWidgets('history distinguishes saved model provenance from legacy data', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({
      'auth_token': 'history-token',
      'selected_patient_id': 73,
      'selected_patient_name': 'Synthetic Patient',
    });
    tester.view.physicalSize = const Size(800, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await http.runWithClient(
      () async {
        await tester.pumpWidget(const MaterialApp(home: HistoryScreen()));
        await tester.pumpAndSettle();

        expect(
          find.text('DiaBD v3 research/demo screening model'),
          findsOneWidget,
        );
        expect(find.text('Screening-model score: 0.64'), findsOneWidget);
        expect(find.text('At/above screening-model threshold'), findsOneWidget);
        expect(
          find.text('Version 3.0.0 - screening threshold 0.06'),
          findsOneWidget,
        );
        expect(find.text('Historical demo heuristic: Low'), findsNWidgets(3));
      },
      () {
        return MockClient((request) async {
          expect(request.headers['authorization'], 'Bearer history-token');
          if (request.url.path == '/assessments/patient/73') {
            return http.Response(
              jsonEncode([
                {
                  'id': 2,
                  'age': 72,
                  'glucose': 165,
                  'systolic_bp': 145,
                  'diastolic_bp': 90,
                  'bmi': 25,
                  'diabetes_risk': 'High',
                  'heart_risk': 'Low',
                  'overall_risk': 'High',
                  'recommendation': 'Synthetic fixture.',
                  'diabetes_prediction_source': 'task13b_diabd_v3_model',
                  'diabetes_prediction_status': 'predicted',
                  'diabetes_model_version': '3.0.0',
                  'diabetes_model_score': 0.64,
                  'diabetes_model_threshold': 0.06,
                  'diabetes_model_classification':
                      'at_or_above_model_threshold',
                },
                {
                  'id': 1,
                  'age': 70,
                  'glucose': 100,
                  'systolic_bp': 120,
                  'diastolic_bp': 80,
                  'bmi': 23,
                  'diabetes_risk': 'Low',
                  'heart_risk': 'Low',
                  'overall_risk': 'Low',
                  'recommendation': 'Historical fixture.',
                },
              ]),
              200,
            );
          }
          if (request.url.path == '/prescriptions/patient/73' ||
              request.url.path == '/medicines/patient/73') {
            return http.Response('[]', 200);
          }
          throw StateError('Unexpected request: ${request.url}');
        });
      },
    );
  });

  testWidgets(
    'history summarizes saved Heart v2 scores without attack claims',
    (tester) async {
      SharedPreferences.setMockInitialValues({
        'auth_token': 'weekly-history-token',
        'selected_patient_id': 73,
        'selected_patient_name': 'Synthetic Patient',
      });
      tester.view.physicalSize = const Size(800, 1400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await http.runWithClient(
        () async {
          await tester.pumpWidget(const MaterialApp(home: HistoryScreen()));
          await tester.pumpAndSettle();

          expect(find.text('Weekly Heart v2 screening record'), findsOneWidget);
          expect(find.text('Latest model score: 42.0%'), findsOneWidget);
          expect(
            find.textContaining('does not forecast an acute heart attack'),
            findsOneWidget,
          );
        },
        () => MockClient((request) async {
          if (request.url.path == '/assessments/patient/73') {
            return http.Response(
              jsonEncode([
                {
                  'id': 2,
                  'created_at': '2026-10-04T10:00:00Z',
                  'heart_risk': 'Low',
                  'overall_risk': 'Low',
                  'heart_prediction_source': 'task13_heart_v2_model',
                  'heart_prediction_status': 'predicted',
                  'heart_model_version': '2.0.0',
                  'heart_model_score': 0.42,
                  'heart_model_threshold': 0.50,
                  'heart_model_classification': 'below_model_threshold',
                },
                {
                  'id': 1,
                  'created_at': '2026-10-01T10:00:00Z',
                  'heart_risk': 'High',
                  'overall_risk': 'High',
                  'heart_prediction_source': 'task13_heart_v2_model',
                  'heart_prediction_status': 'predicted',
                  'heart_model_version': '2.0.0',
                  'heart_model_score': 0.55,
                  'heart_model_threshold': 0.50,
                  'heart_model_classification': 'at_or_above_model_threshold',
                },
              ]),
              200,
            );
          }
          if (request.url.path == '/prescriptions/patient/73' ||
              request.url.path == '/medicines/patient/73') {
            return http.Response('[]', 200);
          }
          throw StateError('Unexpected request: ${request.url}');
        }),
      );
    },
  );

  testWidgets('ML summary reflects the deployed Task 14 models', (
    tester,
  ) async {
    await tester.pumpWidget(const MaterialApp(home: MlResultsScreen()));

    expect(find.text('DiaBD Bangladesh diabetes dataset'), findsOneWidget);
    expect(
      find.textContaining('Unweighted Logistic Regression (v3)'),
      findsOneWidget,
    );
    expect(
      find.textContaining('Balanced Logistic Regression (v2)'),
      findsOneWidget,
    );
    expect(find.textContaining('Integration active'), findsOneWidget);
    expect(find.textContaining('Pima Indians'), findsNothing);
    expect(find.textContaining('rule-based prototype'), findsNothing);
  });
}
