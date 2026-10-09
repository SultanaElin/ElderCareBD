import 'dart:convert';

import 'package:eldercare_bd/models/prescription_extraction.dart';
import 'package:eldercare_bd/services/api_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<T> _withClient<T>(
  Future<http.Response> Function(http.Request request) handler,
  Future<T> Function() action,
) {
  return http.runWithClient(action, () => MockClient(handler));
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({'auth_token': 'ocr-test-token'});
  });

  test('extraction candidate parsing is null-safe and conservative', () {
    final result = PrescriptionExtractionResult.fromJson({
      'prescription_id': '91',
      'ocr_status': 'ready',
      'ocr_engine': 'tesseract',
      'ocr_languages': ['eng'],
      'ocr_text': 'Tab. Napa 500 mg',
      'candidates': [
        {
          'name': 'Napa',
          'strength': '500 mg',
          'dosage': null,
          'frequency': null,
          'duration': null,
          'instructions': null,
          'source_line': 'Tab. Napa 500 mg',
          'confidence': 'medium',
          'warnings': ['Frequency not recognized'],
        },
        'ignored malformed candidate',
      ],
      'warnings': ['OCR text requires review'],
      'reused': true,
    });

    expect(result.prescriptionId, 91);
    expect(result.status, PrescriptionOcrStatus.ready);
    expect(result.ocrLanguages, ['eng']);
    expect(result.reused, isTrue);
    expect(result.candidates, hasLength(1));
    final candidate = result.candidates.single;
    expect(candidate.name, 'Napa');
    expect(candidate.strength, '500 mg');
    expect(candidate.dosage, isEmpty);
    expect(candidate.confidence, MedicineCandidateConfidence.medium);
    expect(candidate.warnings, ['Frequency not recognized']);
  });

  test('candidate edits build complete reviewed confirmation fields', () {
    const original = PrescriptionMedicineCandidate(
      name: 'Napa?',
      strength: '500 mg',
      sourceLine: 'Tab. Napa? 500 mg',
      confidence: MedicineCandidateConfidence.low,
      warnings: ['Medicine name uncertain'],
    );
    final corrected = original.copyWith(
      name: 'Napa',
      dosage: '1 tablet',
      frequency: 'Twice daily',
    );

    expect(corrected.sourceLine, original.sourceLine);
    expect(corrected.warnings, original.warnings);
    expect(corrected.toConfirmationJson(), {
      'name': 'Napa',
      'strength': '500 mg',
      'dosage': '1 tablet',
      'frequency': 'Twice daily',
      'duration': null,
      'instructions': null,
    });
  });

  test('malformed extraction values stay blank instead of being invented', () {
    final result = PrescriptionExtractionResult.fromJson({
      'prescription_id': null,
      'ocr_status': 'unexpected',
      'candidates': [
        {'name': null, 'warnings': 'not-a-list'},
      ],
    });

    expect(result.prescriptionId, isNull);
    expect(result.status, PrescriptionOcrStatus.unknown);
    expect(result.ocrText, isNull);
    expect(result.ocrLanguages, isEmpty);
    expect(result.candidates.single.name, isEmpty);
    expect(result.candidates.single.frequency, isEmpty);
  });

  test('extract request is authenticated, bodyless, and parsed', () async {
    final result = await _withClient((request) async {
      expect(request.method, 'POST');
      expect(
        request.url.toString(),
        '${ApiService.baseUrl}/prescriptions/91/extract',
      );
      expect(request.headers['authorization'], 'Bearer ocr-test-token');
      expect(request.headers.containsKey('content-type'), isFalse);
      expect(request.bodyBytes, isEmpty);
      return http.Response(
        jsonEncode({
          'prescription_id': 91,
          'ocr_status': 'ready',
          'ocr_engine': 'tesseract',
          'ocr_languages': ['eng'],
          'ocr_text': 'Paracetamol 500 mg',
          'candidates': [
            {
              'name': 'Paracetamol',
              'strength': '500 mg',
              'dosage': null,
              'frequency': null,
              'duration': null,
              'instructions': null,
              'source_line': 'Paracetamol 500 mg',
              'confidence': 'high',
              'warnings': <String>[],
            },
          ],
          'warnings': ['Review all OCR fields'],
          'reused': false,
        }),
        200,
      );
    }, () => ApiService.extractPrescription(prescriptionId: 91));

    expect(result.status, PrescriptionOcrStatus.ready);
    expect(result.candidates.single.name, 'Paracetamol');
  });

  test('invalid successful extraction response fails safely', () async {
    await expectLater(
      _withClient(
        (_) async => http.Response(jsonEncode({'ocr_status': 'ready'}), 200),
        () => ApiService.extractPrescription(prescriptionId: 91),
      ),
      throwsA(
        isA<ApiException>().having(
          (error) => error.message,
          'message',
          'The server returned an invalid prescription extraction response.',
        ),
      ),
    );
  });
}
