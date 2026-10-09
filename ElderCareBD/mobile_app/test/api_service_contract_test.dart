import 'dart:convert';

import 'package:eldercare_bd/models/caregiver_verification.dart';
import 'package:eldercare_bd/models/model_prediction.dart';
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

Map<String, dynamic> _requestJson(http.Request request) {
  return jsonDecode(request.body) as Map<String, dynamic>;
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({'auth_token': 'test-access-token'});
  });

  group('caregiver registration contract', () {
    test('maps pending response and sends explicit email channel', () async {
      final result = await _withClient(
        (request) async {
          expect(request.method, 'POST');
          expect(
            request.url.toString(),
            '${ApiService.baseUrl}/auth/register-caregiver',
          );
          expect(request.headers.containsKey('authorization'), isFalse);
          expect(request.headers['content-type'], contains('application/json'));
          expect(_requestJson(request), {
            'name': 'Caregiver One',
            'phone_or_email': 'caregiver@example.invalid',
            'password': 'test-password',
            'channel': 'email',
          });
          return http.Response(
            jsonEncode({
              'message': 'Verification code sent.',
              'caregiver_id': 41,
              'verification_required': true,
              'channel': 'email',
              'destination_hint': 'c***@example.invalid',
              'expires_at': '2026-09-12T10:10:00Z',
              'resend_available_at': '2026-09-12T10:01:00Z',
            }),
            202,
          );
        },
        () {
          return ApiService.registerCaregiver(
            name: 'Caregiver One',
            phoneOrEmail: 'caregiver@example.invalid',
            password: 'test-password',
            channel: CaregiverVerificationChannel.email,
          );
        },
      );

      expect(result.pendingVerification.caregiverId, 41);
      expect(
        result.pendingVerification.channel,
        CaregiverVerificationChannel.email,
      );
      expect(
        result.pendingVerification.destinationHint,
        'c***@example.invalid',
      );
    });

    test('rejects malformed or token-bearing pending responses', () async {
      await expectLater(
        _withClient(
          (_) async => http.Response('<html>not json</html>', 202),
          () => ApiService.registerCaregiver(
            name: 'Caregiver',
            phoneOrEmail: 'caregiver@example.invalid',
            password: 'test-password',
            channel: CaregiverVerificationChannel.email,
          ),
        ),
        throwsA(isA<ApiException>()),
      );
    });

    test('pending duplicate exposes typed context without a token', () async {
      await expectLater(
        _withClient(
          (_) async => http.Response(
            jsonEncode({
              'detail': {
                'code': 'verification_required',
                'message': 'Verification is still required.',
                'caregiver_id': 41,
                'channel': 'email',
                'destination_hint': 'c***@example.invalid',
                'expires_at': '2026-09-12T10:10:00Z',
                'resend_available_at': '2026-09-12T10:01:00Z',
              },
            }),
            409,
          ),
          () => ApiService.registerCaregiver(
            name: 'Caregiver',
            phoneOrEmail: 'caregiver@example.invalid',
            password: 'test-password',
            channel: CaregiverVerificationChannel.email,
          ),
        ),
        throwsA(
          isA<VerificationApiException>()
              .having((error) => error.code, 'code', 'verification_required')
              .having(
                (error) => error.pendingVerification?.caregiverId,
                'caregiver ID',
                41,
              ),
        ),
      );
    });
  });

  group('caregiver login contract', () {
    test(
      'decodes a valid authenticated response and sends login fields',
      () async {
        final result = await _withClient(
          (request) async {
            expect(
              request.url.toString(),
              '${ApiService.baseUrl}/auth/login-caregiver',
            );
            expect(request.headers.containsKey('authorization'), isFalse);
            expect(_requestJson(request), {
              'phone_or_email': 'caregiver@example.invalid',
              'password': 'test-password',
            });
            return http.Response(
              jsonEncode({
                'message': 'Login successful',
                'caregiver_id': 42,
                'name': 'Caregiver',
                'access_token': 'login-token',
                'token_type': 'bearer',
              }),
              200,
            );
          },
          () {
            return ApiService.loginCaregiver(
              phoneOrEmail: 'caregiver@example.invalid',
              password: 'test-password',
            );
          },
        );

        expect(result.caregiverId, 42);
        expect(result.caregiverName, 'Caregiver');
        expect(result.accessToken, 'login-token');
      },
    );

    test('rejects a successful login response without a token', () async {
      await expectLater(
        _withClient(
          (_) async => http.Response(
            jsonEncode({
              'message': 'Login successful',
              'caregiver_id': 42,
              'name': 'Caregiver',
            }),
            200,
          ),
          () => ApiService.loginCaregiver(
            phoneOrEmail: 'caregiver@example.invalid',
            password: 'test-password',
          ),
        ),
        throwsA(
          isA<ApiException>().having(
            (error) => error.message,
            'message',
            'The server returned an invalid authenticated session.',
          ),
        ),
      );
    });

    test('maps verification-required login to typed pending context', () async {
      await expectLater(
        _withClient(
          (_) async => http.Response(
            jsonEncode({
              'detail': {
                'code': 'verification_required',
                'message': 'Verify before login.',
                'caregiver_id': 42,
                'channel': 'sms',
                'destination_hint': '+880******678',
                'expires_at': '2026-09-12T10:10:00Z',
                'resend_available_at': '2026-09-12T10:01:00Z',
              },
            }),
            403,
          ),
          () => ApiService.loginCaregiver(
            phoneOrEmail: '+8801712345678',
            password: 'test-password',
          ),
        ),
        throwsA(
          isA<VerificationApiException>()
              .having((error) => error.code, 'code', 'verification_required')
              .having(
                (error) => error.pendingVerification?.channel,
                'channel',
                CaregiverVerificationChannel.sms,
              ),
        ),
      );
    });

    test('maps an authentication error response', () async {
      await expectLater(
        _withClient(
          (_) async => http.Response(
            jsonEncode({'detail': 'Invalid login credentials'}),
            401,
          ),
          () => ApiService.loginCaregiver(
            phoneOrEmail: 'caregiver@example.invalid',
            password: 'wrong-password',
          ),
        ),
        throwsA(
          isA<VerificationApiException>().having(
            (error) => error.message,
            'message',
            'Invalid login credentials',
          ),
        ),
      );
    });
  });

  group('caregiver OTP API contract', () {
    test(
      'verify preserves a leading zero and never sends bearer auth',
      () async {
        final result = await _withClient(
          (request) async {
            expect(
              request.url.toString(),
              '${ApiService.baseUrl}/auth/verify-otp',
            );
            expect(request.headers.containsKey('authorization'), isFalse);
            expect(_requestJson(request), {
              'caregiver_id': 41,
              'channel': 'email',
              'otp': '042817',
            });
            return http.Response(
              jsonEncode({
                'message': 'Caregiver verified.',
                'caregiver_id': 41,
                'verified': true,
                'verification_required': false,
              }),
              200,
            );
          },
          () => ApiService.verifyCaregiverOtp(
            caregiverId: 41,
            channel: CaregiverVerificationChannel.email,
            otp: '042817',
          ),
        );

        expect(result.caregiverId, 41);
      },
    );

    test('resend parses replacement challenge and timestamps', () async {
      final result = await _withClient(
        (request) async {
          expect(
            request.url.toString(),
            '${ApiService.baseUrl}/auth/resend-otp',
          );
          expect(_requestJson(request), {'caregiver_id': 41, 'channel': 'sms'});
          return http.Response(
            jsonEncode({
              'message': 'New code sent.',
              'caregiver_id': 41,
              'verification_required': true,
              'channel': 'sms',
              'destination_hint': '+880******678',
              'expires_at': '2026-09-12T10:20:00Z',
              'resend_available_at': '2026-09-12T10:11:00Z',
            }),
            200,
          );
        },
        () => ApiService.resendCaregiverOtp(
          caregiverId: 41,
          channel: CaregiverVerificationChannel.sms,
        ),
      );

      expect(result.pendingVerification.expiresAt.isUtc, isTrue);
      expect(result.pendingVerification.destinationHint, '+880******678');
    });

    test('wrong code exposes safe error and attempts remaining', () async {
      await expectLater(
        _withClient(
          (_) async => http.Response(
            jsonEncode({
              'detail': {
                'code': 'invalid_otp',
                'message': 'Raw message is not rendered.',
                'attempts_remaining': 3,
              },
            }),
            400,
          ),
          () => ApiService.verifyCaregiverOtp(
            caregiverId: 41,
            channel: CaregiverVerificationChannel.email,
            otp: '000001',
          ),
        ),
        throwsA(
          isA<VerificationApiException>()
              .having((error) => error.code, 'code', 'invalid_otp')
              .having((error) => error.attemptsRemaining, 'attempts', 3)
              .having(
                (error) => error.message,
                'safe message',
                'That verification code is incorrect. Please try again. 3 attempt(s) remaining.',
              ),
        ),
      );
    });
  });

  group('patient creation contract', () {
    Future<Map<String, dynamic>> createPatient() {
      return ApiService.createPatient(
        caregiverId: 7,
        name: 'Patient One',
        age: 72,
        gender: 'Other',
        phone: 'patient-phone',
        address: 'Patient address',
        emergencyContact: 'Emergency contact',
        hasDiabetes: true,
        hasHeartDisease: false,
        hasHypertension: true,
        hasKidneyDisease: false,
        hasStrokeHistory: false,
        diseaseHistory: 'Existing history',
      );
    }

    test('maps a patient ID and sends the complete patient contract', () async {
      final result = await _withClient((request) async {
        expect(request.url.toString(), '${ApiService.baseUrl}/patients/');
        expect(request.headers['authorization'], 'Bearer test-access-token');
        expect(_requestJson(request), {
          'caregiver_id': 7,
          'name': 'Patient One',
          'age': 72,
          'gender': 'Other',
          'phone': 'patient-phone',
          'address': 'Patient address',
          'emergency_contact': 'Emergency contact',
          'has_diabetes': true,
          'has_heart_disease': false,
          'has_hypertension': true,
          'has_kidney_disease': false,
          'has_stroke_history': false,
          'disease_history': 'Existing history',
        });
        return http.Response(
          jsonEncode({
            'message': 'Patient created successfully',
            'patient_id': 73,
            'name': 'Patient One',
            'caregiver_id': 7,
          }),
          200,
        );
      }, createPatient);

      expect((result['body'] as Map<String, dynamic>)['patient_id'], 73);
    });

    test(
      'normalizes malformed response and preserves backend failure',
      () async {
        final malformed = await _withClient(
          (_) async => http.Response('[]', 200),
          createPatient,
        );
        expect(malformed['body'], {
          'detail': 'The server returned an invalid response.',
        });

        final failure = await _withClient(
          (_) async => http.Response(
            jsonEncode({'detail': 'Not authorized to access this resource.'}),
            403,
          ),
          createPatient,
        );
        expect(failure['statusCode'], 403);
        expect(
          ApiService.errorMessage(
            failure,
            fallback: 'Patient creation failed.',
          ),
          'Not authorized to access this resource.',
        );
      },
    );
  });

  test(
    'assessment creation sends the complete FastAPI field contract',
    () async {
      final result = await _withClient(
        (request) async {
          expect(request.url.toString(), '${ApiService.baseUrl}/assessments/');
          expect(request.headers['authorization'], 'Bearer test-access-token');
          expect(_requestJson(request), {
            'patient_id': 73,
            'age': 72,
            'glucose': 165,
            'systolic_bp': 145,
            'diastolic_bp': 90,
            'bmi': 25.0,
            'height_cm': 160.0,
            'weight_kg': 64.0,
            'note': 'Original caregiver note',
            'chest_pain': true,
            'dizziness': false,
            'shortness_of_breath': true,
            'excessive_thirst': false,
            'fatigue': true,
            'blurred_vision': false,
            'diabetes_risk': 'High',
            'heart_risk': 'Moderate',
            'overall_risk': 'High',
            'recommendation': 'Arrange a clinical review.',
          });
          return http.Response(
            jsonEncode({
              'message': 'Assessment saved successfully',
              'assessment_id': 99,
              'overall_risk': 'High',
            }),
            200,
          );
        },
        () {
          return ApiService.createAssessment(
            patientId: 73,
            age: 72,
            glucose: 165,
            systolicBp: 145,
            diastolicBp: 90,
            bmi: 25.0,
            heightCm: 160.0,
            weightKg: 64.0,
            note: 'Original caregiver note',
            chestPain: true,
            dizziness: false,
            shortnessOfBreath: true,
            excessiveThirst: false,
            fatigue: true,
            blurredVision: false,
            diabetesRisk: 'High',
            heartRisk: 'Moderate',
            overallRisk: 'High',
            recommendation: 'Arrange a clinical review.',
          );
        },
      );

      expect(result['statusCode'], 200);
      expect((result['body'] as Map<String, dynamic>)['assessment_id'], 99);
    },
  );

  group('Task 14 prediction API contracts', () {
    const diabetesInput = DiabetesModelInput(
      age: 72,
      gender: 'Female',
      systolicBp: 145,
      diastolicBp: 90,
      randomGlucoseMmolL: 7.25,
      bmi: 25,
    );
    const heartInput = HeartModelInput(
      age: 72,
      clinicalSex: 'female',
      chestPainType: 'non-anginal pain',
      restingSystolicBpMmHg: 145,
    );

    test('loads authenticated metadata labels and ranges', () async {
      final contracts = await _withClient((request) async {
        expect(request.method, 'GET');
        expect(
          request.url.toString(),
          '${ApiService.baseUrl}/predictions/contracts',
        );
        expect(request.headers['authorization'], 'Bearer test-access-token');
        return http.Response(
          jsonEncode({
            'models': {
              'diabetes': {
                'disease': 'diabetes',
                'available': true,
                'model_version': '3.0.0',
                'model_name': 'DiaBD diabetes status screening model',
                'prediction_source': 'task13b_diabd_v3_model',
                'threshold': 0.06,
                'features': [
                  {'name': 'age', 'minimum': 21, 'maximum': 80},
                  {
                    'name': 'gender',
                    'allowed_values': [0, 1],
                    'value_labels': {'0': 'Female', '1': 'Male'},
                  },
                  {'name': 'systolic_bp', 'minimum': 62, 'maximum': 231},
                  {'name': 'diastolic_bp', 'minimum': 45, 'maximum': 119},
                  {'name': 'glucose', 'minimum': 1.0, 'maximum': 33.46},
                  {'name': 'bmi', 'minimum': 11.47, 'maximum': 54.08},
                ],
              },
              'heart': {
                'disease': 'heart',
                'available': true,
                'model_version': '2.0.0',
                'threshold': 0.53,
                'features': [
                  {'name': 'age', 'minimum': 29, 'maximum': 77},
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
                  {'name': 'trestbps', 'minimum': 94, 'maximum': 200},
                ],
              },
            },
          }),
          200,
        );
      }, ApiService.getPredictionContracts);

      expect(contracts.diabetes?.threshold, 0.06);
      expect(contracts.diabetes?.modelVersion, '3.0.0');
      expect(
        contracts.heart
            ?.featureNamed('sex')
            ?.categoryOptions
            .map((option) => option.label),
        ['female', 'male'],
      );
    });

    test(
      'sends exact authenticated diabetes request and parses score',
      () async {
        final prediction = await _withClient(
          (request) async {
            expect(request.method, 'POST');
            expect(
              request.url.toString(),
              '${ApiService.baseUrl}/predictions/diabetes',
            );
            expect(
              request.headers['authorization'],
              'Bearer test-access-token',
            );
            expect(_requestJson(request), {
              'patient_id': 73,
              'age': 72,
              'gender': 'Female',
              'systolic_bp': 145,
              'diastolic_bp': 90,
              'random_glucose_mmol_l': 7.25,
              'bmi': 25.0,
            });
            return http.Response(
              jsonEncode({
                'patient_id': 73,
                'disease': 'diabetes',
                'prediction_source': 'task13b_diabd_v3_model',
                'model_version': '3.0.0',
                'risk_score': 0.64,
                'classification': 'at_or_above_model_threshold',
                'threshold': 0.06,
                'features_used': {
                  'age': 72,
                  'gender': 0,
                  'systolic_bp': 145,
                  'diastolic_bp': 90,
                  'glucose': 7.25,
                  'bmi': 25,
                },
                'disclaimer': 'Non-diagnostic research screening only.',
              }),
              200,
            );
          },
          () => ApiService.predictDiabetes(patientId: 73, input: diabetesInput),
        );

        expect(prediction.riskScore, 0.64);
        expect(
          prediction.classificationLabel,
          'At/above screening-model threshold',
        );
      },
    );

    test('sends exact lowercase metadata labels in heart request', () async {
      final prediction = await _withClient((request) async {
        expect(request.method, 'POST');
        expect(
          request.url.toString(),
          '${ApiService.baseUrl}/predictions/heart',
        );
        expect(request.headers['authorization'], 'Bearer test-access-token');
        expect(_requestJson(request), {
          'patient_id': 73,
          'age': 72,
          'clinical_sex': 'female',
          'chest_pain_type': 'non-anginal pain',
          'blood_pressure_context': 'resting_systolic',
          'resting_systolic_bp_mm_hg': 145,
        });
        return http.Response(
          jsonEncode({
            'patient_id': 73,
            'disease': 'heart',
            'prediction_source': 'task13_heart_v2_model',
            'model_version': '2.0.0',
            'risk_score': 0.58,
            'classification': 'at_or_above_model_threshold',
            'threshold': 0.53,
            'features_used': {'age': 72, 'sex': 0, 'cp': 2, 'trestbps': 145},
            'disclaimer': 'Non-diagnostic research screening only.',
          }),
          200,
        );
      }, () => ApiService.predictHeart(patientId: 73, input: heartInput));

      expect(prediction.riskScore, 0.58);
    });

    test(
      'assessment save includes exact optional model input blocks',
      () async {
        await _withClient(
          (request) async {
            expect(
              request.url.toString(),
              '${ApiService.baseUrl}/assessments/',
            );
            expect(
              request.headers['authorization'],
              'Bearer test-access-token',
            );
            final payload = _requestJson(request);
            expect(payload['diabetes_model_input'], {
              'age': 72,
              'gender': 'Female',
              'systolic_bp': 145,
              'diastolic_bp': 90,
              'random_glucose_mmol_l': 7.25,
              'bmi': 25.0,
            });
            expect(payload['heart_model_input'], {
              'age': 72,
              'clinical_sex': 'female',
              'chest_pain_type': 'non-anginal pain',
              'blood_pressure_context': 'resting_systolic',
              'resting_systolic_bp_mm_hg': 145,
            });
            expect(payload.keys.toSet(), {
              'patient_id',
              'age',
              'glucose',
              'systolic_bp',
              'diastolic_bp',
              'bmi',
              'height_cm',
              'weight_kg',
              'note',
              'chest_pain',
              'dizziness',
              'shortness_of_breath',
              'excessive_thirst',
              'fatigue',
              'blurred_vision',
              'diabetes_risk',
              'heart_risk',
              'overall_risk',
              'recommendation',
              'diabetes_model_input',
              'heart_model_input',
            });
            return http.Response(
              jsonEncode({
                'assessment_id': 99,
                'predictions': {
                  'diabetes': {
                    'disease': 'diabetes',
                    'prediction_source': 'task13b_diabd_v3_model',
                    'prediction_status': 'predicted',
                    'model_version': '3.0.0',
                    'risk_score': 0.64,
                    'threshold': 0.06,
                    'classification': 'at_or_above_model_threshold',
                    'disclaimer': 'Non-diagnostic.',
                  },
                },
              }),
              200,
            );
          },
          () {
            return ApiService.createAssessment(
              patientId: 73,
              age: 72,
              glucose: 165,
              systolicBp: 145,
              diastolicBp: 90,
              bmi: 25,
              heightCm: 160,
              weightKg: 64,
              note: 'Original caregiver note',
              chestPain: true,
              dizziness: false,
              shortnessOfBreath: true,
              excessiveThirst: false,
              fatigue: true,
              blurredVision: false,
              diabetesRisk: 'High',
              heartRisk: 'High',
              overallRisk: 'High',
              recommendation: 'Arrange a clinical review.',
              diabetesModelInput: diabetesInput,
              heartModelInput: heartInput,
            );
          },
        );
      },
    );

    test('model-unavailable response becomes a friendly exception', () async {
      await expectLater(
        _withClient(
          (_) async => http.Response(
            jsonEncode({'detail': 'Heart research model is unavailable.'}),
            503,
          ),
          () => ApiService.predictHeart(patientId: 73, input: heartInput),
        ),
        throwsA(
          isA<ApiException>().having(
            (error) => error.message,
            'message',
            'Heart research model is unavailable.',
          ),
        ),
      );
    });

    test('malformed successful model output is rejected', () async {
      await expectLater(
        _withClient(
          (_) async => http.Response(
            jsonEncode({
              'disease': 'diabetes',
              'prediction_source': 'task13b_diabd_v3_model',
              'model_version': '3.0.0',
              'risk_score': 5.0,
              'threshold': 0.06,
              'classification': 'medium',
              'disclaimer': 'Malformed fixture.',
            }),
            200,
          ),
          () => ApiService.predictDiabetes(patientId: 73, input: diabetesInput),
        ),
        throwsA(
          isA<ApiException>().having(
            (error) => error.message,
            'message',
            'The server returned an invalid research-model prediction.',
          ),
        ),
      );
    });
  });

  test('network failure is mapped to a friendly API exception', () async {
    await expectLater(
      _withClient(
        (request) async => throw http.ClientException('offline', request.url),
        () => ApiService.loginCaregiver(
          phoneOrEmail: 'caregiver@example.invalid',
          password: 'test-password',
        ),
      ),
      throwsA(
        isA<ApiException>().having(
          (error) => error.message,
          'message',
          'Could not connect to the server. Please try again.',
        ),
      ),
    );
  });
}
