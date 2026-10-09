import 'package:eldercare_bd/app.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('root application widget can be instantiated', () {
    const app = ElderCareBDApp();

    expect(app, isA<Widget>());
  });
}
