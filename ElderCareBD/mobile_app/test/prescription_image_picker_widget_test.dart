import 'dart:convert';
import 'dart:typed_data';

import 'package:eldercare_bd/screens/prescription_input_screen.dart';
import 'package:eldercare_bd/services/prescription_image_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

final Uint8List _onePixelPng = base64Decode(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
);

class _FakePicker implements PrescriptionImagePicker {
  final PickedPrescriptionImage? recovered;
  final List<PrescriptionImageSource> sources = [];
  int recoveryCalls = 0;

  _FakePicker({this.recovered});

  @override
  Future<PickedPrescriptionImage?> pick(PrescriptionImageSource source) async {
    sources.add(source);
    return PickedPrescriptionImage(
      bytes: _onePixelPng,
      name: source == PrescriptionImageSource.camera
          ? 'camera.png'
          : 'gallery.png',
    );
  }

  @override
  Future<PickedPrescriptionImage?> recoverLostImage() async {
    recoveryCalls += 1;
    return recovered;
  }
}

Future<void> _tapVisible(WidgetTester tester, Finder finder) async {
  ScaffoldMessenger.of(
    tester.element(find.byType(Scaffold).first),
  ).clearSnackBars();
  await tester.pumpAndSettle();
  await Scrollable.ensureVisible(tester.element(finder), alignment: 0.5);
  await tester.pumpAndSettle();
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('recovers a lost Android prescription image', (tester) async {
    final picker = _FakePicker(
      recovered: PickedPrescriptionImage(
        bytes: _onePixelPng,
        name: 'recovered.png',
      ),
    );

    await tester.pumpWidget(
      MaterialApp(home: PrescriptionInputScreen(imagePicker: picker)),
    );
    await tester.pumpAndSettle();

    expect(picker.recoveryCalls, 1);
    expect(find.text('Selected: recovered.png'), findsOneWidget);
  });

  testWidgets('camera/gallery selection previews and removes an image', (
    tester,
  ) async {
    final picker = _FakePicker();
    await tester.pumpWidget(
      MaterialApp(home: PrescriptionInputScreen(imagePicker: picker)),
    );
    await tester.pumpAndSettle();

    await _tapVisible(tester, find.text('Take photo'));
    expect(picker.sources, [PrescriptionImageSource.camera]);
    expect(find.text('Selected: camera.png'), findsOneWidget);

    await _tapVisible(tester, find.text('Choose from gallery'));
    expect(picker.sources, [
      PrescriptionImageSource.camera,
      PrescriptionImageSource.gallery,
    ]);
    expect(find.text('Selected: gallery.png'), findsOneWidget);

    await _tapVisible(tester, find.text('Remove selected image'));
    expect(find.text('No prescription image selected'), findsOneWidget);
  });
}
