import 'dart:convert';

import 'package:eldercare_bd/screens/assessment_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> _contracts() => {
  'models': {
    'diabetes': {
      'disease': 'diabetes',
      'available': true,
      'model_version': '3.0.0',
      'model_name': 'DiaBD diabetes status screening model',
      'prediction_source': 'task13b_diabd_v3_model',
      'threshold': 0.06,
      'features': [
        {'name': 'age', 'type': 'integer', 'minimum': 21, 'maximum': 80},
        {
          'name': 'gender',
          'type': 'integer',
          'allowed_values': [0, 1],
          'value_labels': {'0': 'Female', '1': 'Male'},
        },
        {
          'name': 'systolic_bp',
          'type': 'integer',
          'minimum': 62,
          'maximum': 231,
        },
        {
          'name': 'diastolic_bp',
          'type': 'integer',
          'minimum': 45,
          'maximum': 119,
        },
        {
          'name': 'glucose',
          'type': 'number',
          'minimum': 1.0,
          'maximum': 33.46,
          'unit': 'mmol/L',
        },
        {'name': 'bmi', 'type': 'number', 'minimum': 11.47, 'maximum': 54.08},
      ],
    },
    'heart': {
      'disease': 'heart',
      'available': true,
      'model_version': '2.0.0',
      'prediction_source': 'task13_heart_v2_model',
      'threshold': 0.53,
      'features': [
        {'name': 'age', 'type': 'integer', 'minimum': 29, 'maximum': 77},
        {
          'name': 'sex',
          'allowed_values': [0, 1],
          'value_labels': {'0': 'female', '1': 'male'},
        },
        {
          'name': 'cp',
          'allowed_values': [0, 1, 2, 3],
          'value_labels': {
            '0': 'typical angina',
            '1': 'atypical angina',
            '2': 'non-anginal pain',
            '3': 'asymptomatic',
          },
        },
        {'name': 'trestbps', 'type': 'integer', 'minimum': 94, 'maximum': 200},
      ],
    },
  },
};

Future<void> _pumpAssessment(
  WidgetTester tester, {
  required String gender,
  required bool hasDiabetes,
  Size viewport = const Size(900, 2600),
  double textScale = 1,
}) async {
  SharedPreferences.setMockInitialValues({
    'auth_token': 'task14-widget-token',
    'selected_patient_id': 73,
    'selected_patient_name': 'Synthetic Patient',
  });
  tester.view.physicalSize = viewport;
  tester.view.devicePixelRatio = 1;

  await http.runWithClient(
    () async {
      await tester.pumpWidget(
        MaterialApp(
          builder: (context, child) => MediaQuery(
            data: MediaQueryData(textScaler: TextScaler.linear(textScale)),
            child: child!,
          ),
          home: const AssessmentScreen(),
        ),
      );
      await tester.pumpAndSettle();
    },
    () => MockClient((request) async {
      expect(request.headers['authorization'], 'Bearer task14-widget-token');
      if (request.url.path == '/predictions/contracts') {
        return http.Response(jsonEncode(_contracts()), 200);
      }
      if (request.url.path == '/patients/73') {
        return http.Response(
          jsonEncode({
            'id': 73,
            'name': 'Synthetic Patient',
            'age': 72,
            'gender': gender,
            'has_diabetes': hasDiabetes,
          }),
          200,
        );
      }
      throw StateError('Unexpected request: ${request.url}');
    }),
  );
}

Finder _textFieldWithLabel(String label) => find.byWidgetPredicate(
  (widget) => widget is TextField && widget.decoration?.labelText == label,
  description: 'TextField labelled "$label"',
);

Future<void> _enterRequiredAssessmentValues(WidgetTester tester) async {
  await tester.enterText(_textFieldWithLabel('Age'), '72');
  await tester.enterText(
    _textFieldWithLabel('General glucose reading (mmol/L)'),
    '9.17',
  );
  await tester.enterText(_textFieldWithLabel('Systolic BP'), '145');
  await tester.enterText(_textFieldWithLabel('Diastolic BP'), '90');
  await tester.enterText(_textFieldWithLabel('Height (feet)'), '5');
  await tester.enterText(_textFieldWithLabel('Height (inches)'), '7');
  await tester.enterText(_textFieldWithLabel('Weight (kg)'), '72');
}

Future<void> _tapGenerateAssessment(WidgetTester tester) async {
  final generateButton = find.text('Generate Risk Assessment');
  await tester.ensureVisible(generateButton);
  await tester.tap(generateButton);
  await tester.pumpAndSettle();
}

Future<Map<String, int>> _submitWithoutDiabetesPrediction(
  WidgetTester tester, {
  required String gender,
  required bool hasDiabetes,
}) async {
  var diabetesRequests = 0;
  var assessmentRequests = 0;

  SharedPreferences.setMockInitialValues({
    'auth_token': 'task14-widget-token',
    'selected_patient_id': 73,
    'selected_patient_name': 'Synthetic Patient',
  });
  tester.view.physicalSize = const Size(900, 2600);
  tester.view.devicePixelRatio = 1;

  await http.runWithClient(
    () async {
      await tester.pumpWidget(const MaterialApp(home: AssessmentScreen()));
      await tester.pumpAndSettle();
      await _enterRequiredAssessmentValues(tester);
      await _tapGenerateAssessment(tester);
    },
    () => MockClient((request) async {
      expect(request.headers['authorization'], 'Bearer task14-widget-token');
      if (request.url.path == '/predictions/contracts') {
        return http.Response(jsonEncode(_contracts()), 200);
      }
      if (request.url.path == '/patients/73') {
        return http.Response(
          jsonEncode({
            'id': 73,
            'name': 'Synthetic Patient',
            'age': 72,
            'gender': gender,
            'has_diabetes': hasDiabetes,
          }),
          200,
        );
      }
      if (request.url.path == '/predictions/diabetes') {
        diabetesRequests++;
        return http.Response('{}', 500);
      }
      if (request.url.path == '/predictions/heart') {
        fail('Heart prediction must not run without the optional inputs.');
      }
      if (request.url.path == '/assessments/') {
        assessmentRequests++;
        final payload = jsonDecode(request.body) as Map<String, dynamic>;
        expect(payload.containsKey('diabetes_model_input'), isFalse);
        expect(payload.containsKey('heart_model_input'), isFalse);
        return http.Response(jsonEncode({'assessment_id': 501}), 201);
      }
      throw StateError('Unexpected request: ${request.url}');
    }),
  );

  return {
    'diabetesRequests': diabetesRequests,
    'assessmentRequests': assessmentRequests,
  };
}

void main() {
  testWidgets(
    'assessment sections avoid ListTile framework errors on a narrow phone',
    (tester) async {
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await _pumpAssessment(
        tester,
        gender: 'Female',
        hasDiabetes: false,
        viewport: const Size(320, 780),
      );

      expect(find.byType(CheckboxListTile), findsNothing);
      expect(
        tester
            .widget<TextField>(
              _textFieldWithLabel('General glucose reading (mmol/L)'),
            )
            .decoration
            ?.helperMaxLines,
        3,
      );
      expect(
        tester
            .widget<TextField>(_textFieldWithLabel('Weight (kg)'))
            .decoration
            ?.helperMaxLines,
        2,
      );
      for (final key in const [
        Key('assessment-section-basic'),
        Key('assessment-section-models'),
        Key('assessment-section-symptoms'),
        Key('assessment-section-notes'),
        Key('assessment-section-submit'),
      ]) {
        await tester.scrollUntilVisible(
          find.byKey(key),
          320,
          scrollable: find.byType(Scrollable).first,
        );
        await tester.pump();
        expect(tester.takeException(), isNull);
      }
    },
  );

  testWidgets(
    'assessment remains exception-free with enlarged accessibility text',
    (tester) async {
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await _pumpAssessment(
        tester,
        gender: 'Female',
        hasDiabetes: false,
        viewport: const Size(390, 844),
        textScale: 1.8,
      );

      await tester.scrollUntilVisible(
        find.byKey(const Key('confirm-random-glucose-mmol-l')),
        500,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(
        find.descendant(
          of: find.byKey(const Key('confirm-random-glucose-mmol-l')),
          matching: find.byType(Checkbox),
        ),
      );
      await tester.pump();
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'DiaBD contract renders decimal mmol/L input without OGTT field',
    (tester) async {
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await _pumpAssessment(tester, gender: 'Female', hasDiabetes: false);

      expect(find.text('DiaBD diabetes status screening'), findsOneWidget);
      expect(
        find.byKey(const Key('random-glucose-mmol-l-input')),
        findsOneWidget,
      );
      expect(
        find.byKey(const Key('confirm-random-glucose-mmol-l')),
        findsOneWidget,
      );
      expect(find.textContaining('mmol/L'), findsWidgets);
      final diaBdGlucoseField = tester.widget<TextField>(
        find.byKey(const Key('random-glucose-mmol-l-input')),
      );
      expect(diaBdGlucoseField.decoration?.hintText, 'Example: 6.1 or 7.00');
      expect(diaBdGlucoseField.decoration?.helperMaxLines, 3);
      expect(
        find.byKey(const Key('two-hour-ogtt-glucose-input')),
        findsNothing,
      );

      await tester.enterText(
        find.byKey(const Key('random-glucose-mmol-l-input')),
        '6.1',
      );
      expect(find.text('6.1'), findsOneWidget);

      await tester.enterText(
        find.byKey(const Key('random-glucose-mmol-l-input')),
        '7.00',
      );
      expect(find.text('7.00'), findsOneWidget);
    },
  );

  testWidgets('Other gender prevents DiaBD input instead of fabricating code', (
    tester,
  ) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await _pumpAssessment(tester, gender: 'Other', hasDiabetes: false);

    expect(
      find.byKey(const Key('unsupported-diabetes-gender-message')),
      findsOneWidget,
    );
    expect(find.byKey(const Key('random-glucose-mmol-l-input')), findsNothing);
  });

  testWidgets('known diabetes shows non-applicable bypass and no model input', (
    tester,
  ) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await _pumpAssessment(tester, gender: 'Female', hasDiabetes: true);

    expect(
      find.byKey(const Key('known-diabetes-bypass-message')),
      findsOneWidget,
    );
    expect(find.byKey(const Key('random-glucose-mmol-l-input')), findsNothing);
  });

  testWidgets('Heart v2 renders exact metadata categories and resting BP input', (
    tester,
  ) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await _pumpAssessment(tester, gender: 'Female', hasDiabetes: false);

    final clinicalSexFinder = find.byKey(
      const ValueKey('heart-clinical-sex-input-female|male'),
    );
    final chestPainFinder = find.byKey(
      const ValueKey(
        'heart-chest-pain-type-input-typical angina|atypical angina|non-anginal pain|asymptomatic',
      ),
    );

    expect(clinicalSexFinder, findsOneWidget);
    expect(chestPainFinder, findsOneWidget);
    expect(find.byKey(const Key('confirm-resting-systolic')), findsOneWidget);
    expect(find.text('Clinical sex for this model'), findsOneWidget);
    expect(find.text('UCI-compatible chest-pain type'), findsOneWidget);
    expect(
      find.text('The systolic BP above was measured at rest'),
      findsOneWidget,
    );

    expect(find.text('Female', skipOffstage: false), findsWidgets);
    expect(find.text('Male', skipOffstage: false), findsWidgets);
    expect(find.text('Typical angina', skipOffstage: false), findsOneWidget);
    expect(find.text('Atypical angina', skipOffstage: false), findsOneWidget);
    expect(find.text('Non-anginal pain', skipOffstage: false), findsOneWidget);
    expect(find.text('Asymptomatic', skipOffstage: false), findsOneWidget);
  });

  testWidgets('Other gender submits without a diabetes prediction request', (
    tester,
  ) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final calls = await _submitWithoutDiabetesPrediction(
      tester,
      gender: 'Other',
      hasDiabetes: false,
    );

    expect(calls['diabetesRequests'], 0);
    expect(calls['assessmentRequests'], 1);
    expect(find.text('Risk Result'), findsOneWidget);
  });

  testWidgets('known diabetes submits without a diabetes prediction request', (
    tester,
  ) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final calls = await _submitWithoutDiabetesPrediction(
      tester,
      gender: 'Female',
      hasDiabetes: true,
    );

    expect(calls['diabetesRequests'], 0);
    expect(calls['assessmentRequests'], 1);
    expect(find.text('Risk Result'), findsOneWidget);
    expect(find.text('Screening not applicable'), findsOneWidget);
  });

  testWidgets('prediction failure does not block assessment save or result', (
    tester,
  ) async {
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var diabetesRequests = 0;
    var assessmentRequests = 0;

    SharedPreferences.setMockInitialValues({
      'auth_token': 'task14-widget-token',
      'selected_patient_id': 73,
      'selected_patient_name': 'Synthetic Patient',
    });
    tester.view.physicalSize = const Size(900, 2600);
    tester.view.devicePixelRatio = 1;

    await http.runWithClient(
      () async {
        await tester.pumpWidget(const MaterialApp(home: AssessmentScreen()));
        await tester.pumpAndSettle();
        await _enterRequiredAssessmentValues(tester);
        await tester.enterText(
          find.byKey(const Key('random-glucose-mmol-l-input')),
          '7.25',
        );
        await tester.tap(
          find.descendant(
            of: find.byKey(const Key('confirm-random-glucose-mmol-l')),
            matching: find.byType(Checkbox),
          ),
        );
        await tester.pump();
        await _tapGenerateAssessment(tester);
      },
      () => MockClient((request) async {
        expect(request.headers['authorization'], 'Bearer task14-widget-token');
        if (request.url.path == '/predictions/contracts') {
          return http.Response(jsonEncode(_contracts()), 200);
        }
        if (request.url.path == '/patients/73') {
          return http.Response(
            jsonEncode({
              'id': 73,
              'name': 'Synthetic Patient',
              'age': 72,
              'gender': 'Female',
              'has_diabetes': false,
            }),
            200,
          );
        }
        if (request.url.path == '/predictions/diabetes') {
          diabetesRequests++;
          return http.Response(
            jsonEncode({'detail': 'Synthetic inference outage.'}),
            503,
          );
        }
        if (request.url.path == '/predictions/heart') {
          fail('Heart prediction must not run without the optional inputs.');
        }
        if (request.url.path == '/assessments/') {
          assessmentRequests++;
          final payload = jsonDecode(request.body) as Map<String, dynamic>;
          expect(payload['diabetes_model_input'], {
            'age': 72,
            'gender': 'Female',
            'systolic_bp': 145,
            'diastolic_bp': 90,
            'random_glucose_mmol_l': 7.25,
            'bmi': 24.9,
          });
          return http.Response(jsonEncode({'assessment_id': 502}), 201);
        }
        throw StateError('Unexpected request: ${request.url}');
      }),
    );

    expect(diabetesRequests, 1);
    expect(assessmentRequests, 1);
    expect(find.text('Risk Result'), findsOneWidget);
    expect(find.textContaining('could not complete screening'), findsOneWidget);
  });
}
