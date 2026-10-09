import 'package:eldercare_bd/models/daily_observation.dart';
import 'package:eldercare_bd/models/model_prediction.dart';
import 'package:eldercare_bd/screens/daily_health_update_screen.dart';
import 'package:eldercare_bd/screens/risk_result_screen.dart';
import 'package:eldercare_bd/services/api_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

DailyObservation _observation({
  int id = 9,
  DailyObservationDraft values = const DailyObservationDraft(),
}) {
  return DailyObservation(
    id: id,
    patientId: 73,
    observationDate: DateTime(2026, 10, 9),
    recordedAt: DateTime(2026, 10, 9, 8),
    createdAt: DateTime(2026, 10, 9, 8),
    updatedAt: DateTime(2026, 10, 9, 8),
    values: values,
  );
}

Future<void> _pumpDaily(
  WidgetTester tester, {
  DailyObservation? existing,
  TodayObservationCreator? creator,
  ObservationUpdater? updater,
  TodayObservationLoader? loader,
  Size size = const Size(400, 800),
  double textScale = 1,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    MaterialApp(
      builder: (context, child) => MediaQuery(
        data: MediaQueryData(
          size: size,
          textScaler: TextScaler.linear(textScale),
        ),
        child: child!,
      ),
      home: DailyHealthUpdateScreen(
        patientIdLoader: () async => 73,
        patientNameLoader: () async => 'Synthetic Patient',
        observationLoader: loader ?? (_) async => existing,
        observationCreator: creator,
        observationUpdater: updater,
      ),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _enter(WidgetTester tester, String key, String value) async {
  final finder = find.byKey(Key(key));
  await tester.ensureVisible(finder.first);
  await tester.pumpAndSettle();
  await tester.enterText(finder.first, value);
}

Future<void> _select(WidgetTester tester, String key, String option) async {
  final finder = find.byKey(Key(key));
  await tester.ensureVisible(finder.first);
  await tester.pumpAndSettle();
  await tester.tap(finder.first);
  await tester.pumpAndSettle();
  await tester.tap(find.text(option).last);
  await tester.pumpAndSettle();
}

Future<void> _save(WidgetTester tester) async {
  final button = find.byType(ElevatedButton);
  tester.testTextInput.hide();
  FocusManager.instance.primaryFocus?.unfocus();
  await tester.pumpAndSettle();
  await tester.scrollUntilVisible(
    button,
    300,
    scrollable: find.byType(Scrollable).first,
  );
  await tester.pumpAndSettle();
  await tester.tap(button);
  await tester.pumpAndSettle();
}

DiseasePrediction _heartPrediction(double score, double threshold) {
  return DiseasePrediction(
    disease: 'heart',
    predictionSource: 'task13_heart_v2_model',
    predictionStatus: 'predicted',
    modelVersion: '2.0.0',
    riskScore: score,
    threshold: threshold,
    classification: score >= threshold
        ? 'at_or_above_model_threshold'
        : 'below_model_threshold',
    disclaimer: 'Research screening only.',
  );
}

Future<void> _pumpHeart(
  WidgetTester tester, {
  required double score,
  double threshold = 0.5,
}) async {
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: HeartScreeningModelResult(
            prediction: _heartPrediction(score, threshold),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  group("Today's Health Update", () {
    testWidgets('01 empty today form', (tester) async {
      await _pumpDaily(tester);
      expect(
        find.text('No health update has been recorded today.'),
        findsOneWidget,
      );
      final systolic = tester.widget<TextFormField>(
        find.byKey(const Key('systolic-input')),
      );
      expect(systolic.controller!.text, isEmpty);
    });

    testWidgets('02 preloads an existing observation', (tester) async {
      await _pumpDaily(
        tester,
        existing: _observation(
          values: const DailyObservationDraft(
            systolicBp: 128,
            diastolicBp: 78,
            pulseBpm: 71,
            notes: 'Morning reading',
          ),
        ),
      );
      expect(find.text("Editing today's saved health update."), findsOneWidget);
      expect(
        tester
            .widget<TextFormField>(find.byKey(const Key('systolic-input')))
            .controller!
            .text,
        '128',
      );
      await tester.ensureVisible(find.text('Morning reading').first);
      await tester.pumpAndSettle();
      expect(find.text('Morning reading'), findsOneWidget);
    });

    testWidgets('03 successfully creates and displays saved values', (
      tester,
    ) async {
      DailyObservationDraft? sent;
      await _pumpDaily(
        tester,
        creator: (patientId, draft) async {
          expect(patientId, 73);
          sent = draft;
          return _observation(values: draft);
        },
      );
      await _enter(tester, 'pulse-input', '72');
      await _save(tester);
      expect(sent!.pulseBpm, 72);
      expect(
        find.text("Today's health update was saved successfully."),
        findsOneWidget,
      );
      expect(find.text("Editing today's saved health update."), findsOneWidget);
    });

    testWidgets('04 successfully updates the existing record', (tester) async {
      int? updatedId;
      DailyObservationDraft? sent;
      await _pumpDaily(
        tester,
        existing: _observation(
          values: const DailyObservationDraft(pulseBpm: 70),
        ),
        updater: (patientId, observationId, draft) async {
          updatedId = observationId;
          sent = draft;
          return _observation(values: draft);
        },
      );
      await _enter(tester, 'pulse-input', '75');
      await _save(tester);
      expect(updatedId, 9);
      expect(sent!.pulseBpm, 75);
      expect(find.text('Update Health Update'), findsOneWidget);
    });

    testWidgets('05 permits optional partial fields', (tester) async {
      DailyObservationDraft? sent;
      await _pumpDaily(
        tester,
        creator: (_, draft) async {
          sent = draft;
          return _observation(values: draft);
        },
      );
      await _enter(tester, 'notes-input', 'Patient slept well.');
      await _save(tester);
      expect(sent!.notes, 'Patient slept well.');
      expect(sent!.systolicBp, isNull);
      expect(sent!.glucoseValue, isNull);
    });

    testWidgets('06 requires and preserves explicit unit selection', (
      tester,
    ) async {
      DailyObservationDraft? sent;
      await _pumpDaily(
        tester,
        creator: (_, draft) async {
          sent = draft;
          return _observation(values: draft);
        },
      );
      await _enter(tester, 'glucose-input', '6.1');
      await _select(tester, 'glucose-unit-input', 'mmol/L');
      await _enter(tester, 'temperature-input', '36.8');
      await _select(tester, 'temperature-unit-input', 'C');
      await _save(tester);
      expect(sent!.glucoseUnit, 'mmol/L');
      expect(sent!.temperatureUnit, 'C');
    });

    testWidgets('07 validates blood pressure relationship', (tester) async {
      await _pumpDaily(tester);
      await _enter(tester, 'systolic-input', '110');
      await _enter(tester, 'diastolic-input', '115');
      await _save(tester);
      expect(
        find.text('Diastolic BP must be lower than systolic BP.'),
        findsOneWidget,
      );
    });

    testWidgets('08 validates SpO2 range', (tester) async {
      await _pumpDaily(tester);
      await _enter(tester, 'spo2-input', '101');
      await _save(tester);
      expect(find.text('SpO₂ must be between 0 and 100.'), findsOneWidget);
    });

    testWidgets('09 validates pulse range', (tester) async {
      await _pumpDaily(tester);
      await _enter(tester, 'pulse-input', '221');
      await _save(tester);
      expect(find.text('Pulse must be between 30 and 220.'), findsOneWidget);
    });

    testWidgets('10 validates temperature using selected unit', (tester) async {
      await _pumpDaily(tester);
      await _enter(tester, 'temperature-input', '44');
      await _select(tester, 'temperature-unit-input', 'C');
      await _save(tester);
      expect(find.text('Temperature must be 32–43 C.'), findsOneWidget);
    });

    testWidgets('11 validates glucose using selected unit', (tester) async {
      await _pumpDaily(tester);
      await _enter(tester, 'glucose-input', '700');
      await _select(tester, 'glucose-unit-input', 'mg/dL');
      await _save(tester);
      expect(find.text('Glucose must be 20–600 mg/dL.'), findsOneWidget);
    });

    testWidgets('12 displays backend validation errors', (tester) async {
      await _pumpDaily(
        tester,
        creator: (_, _) async => throw const ApiException(
          'Input should be within the accepted range.',
          statusCode: 422,
        ),
      );
      await _enter(tester, 'notes-input', 'Test note');
      await _save(tester);
      expect(
        find.text('Input should be within the accepted range.'),
        findsOneWidget,
      );
    });

    testWidgets('13 displays network failure without losing the form', (
      tester,
    ) async {
      await _pumpDaily(
        tester,
        creator: (_, _) async =>
            throw const ApiException('Could not connect to the server.'),
      );
      await _enter(tester, 'notes-input', 'Keep this text');
      await _save(tester);
      expect(find.text('Could not connect to the server.'), findsOneWidget);
      expect(find.text('Keep this text'), findsOneWidget);
    });

    testWidgets('14 narrow phone layout has no framework overflow', (
      tester,
    ) async {
      await _pumpDaily(tester, size: const Size(320, 640));
      await tester.drag(
        find.byType(SingleChildScrollView),
        const Offset(0, -500),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });

    testWidgets('15 180 percent text scale remains usable', (tester) async {
      await _pumpDaily(tester, size: const Size(360, 740), textScale: 1.8);
      await tester.drag(
        find.byType(SingleChildScrollView),
        const Offset(0, -700),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.byType(ElevatedButton), findsOneWidget);
    });
  });

  group('Heart screening result UX', () {
    testWidgets('16 below-threshold wording is non-diagnostic', (tester) async {
      await _pumpHeart(tester, score: 0.49);
      expect(find.text('Below screening threshold'), findsOneWidget);
      expect(
        find.text(
          'The current inputs were not flagged by the heart screening model.',
        ),
        findsOneWidget,
      );
      expect(
        find.text('This is a screening result, not a diagnosis.'),
        findsOneWidget,
      );
    });

    testWidgets('17 at-threshold wording requires attention', (tester) async {
      await _pumpHeart(tester, score: 0.5);
      expect(find.text('Screening result requires attention'), findsOneWidget);
      expect(
        find.text('This result does not confirm heart disease.'),
        findsOneWidget,
      );
    });

    testWidgets('18 above-threshold wording requires attention', (
      tester,
    ) async {
      await _pumpHeart(tester, score: 0.8);
      expect(
        find.text(
          'The current inputs were flagged at or above the screening threshold. Consider discussing the result with a healthcare professional.',
        ),
        findsOneWidget,
      );
    });

    testWidgets('19 technical score remains secondary and collapsible', (
      tester,
    ) async {
      await _pumpHeart(tester, score: 0.42);
      expect(find.text('Model score: 0.42').hitTestable(), findsNothing);
      await tester.tap(find.text('Technical details'));
      await tester.pumpAndSettle();
      expect(find.text('Model: Heart v2'), findsOneWidget);
      expect(find.text('Model score: 0.42').hitTestable(), findsOneWidget);
      expect(find.text('Screening threshold: 0.50'), findsOneWidget);
    });

    testWidgets('20 heart result contains no diagnostic wording', (
      tester,
    ) async {
      await _pumpHeart(tester, score: 0.61);
      final text = tester
          .widgetList<Text>(find.byType(Text))
          .map((widget) => widget.data ?? '')
          .join(' ')
          .toLowerCase();
      expect(text, isNot(contains('heart disease detected')));
      expect(text, isNot(contains('you have heart disease')));
      expect(text, isNot(contains('high chance of heart disease')));
      expect(text, isNot(contains('heart attack probability')));
    });

    testWidgets('21 model score is not presented as percentage risk', (
      tester,
    ) async {
      await _pumpHeart(tester, score: 0.61);
      await tester.tap(find.text('Technical details'));
      await tester.pumpAndSettle();
      final text = tester
          .widgetList<Text>(find.byType(Text))
          .map((widget) => widget.data ?? '')
          .join(' ')
          .toLowerCase();
      expect(text, isNot(contains('61%')));
      expect(text, isNot(contains('heart disease risk')));
      expect(text, contains('model score: 0.61'));
    });
  });
}
