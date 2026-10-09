import 'dart:typed_data';

import 'package:image_picker/image_picker.dart';

enum PrescriptionImageSource { camera, gallery }

class PickedPrescriptionImage {
  final Uint8List bytes;
  final String name;

  const PickedPrescriptionImage({required this.bytes, required this.name});
}

abstract interface class PrescriptionImagePicker {
  Future<PickedPrescriptionImage?> pick(PrescriptionImageSource source);

  Future<PickedPrescriptionImage?> recoverLostImage();
}

class DevicePrescriptionImagePicker implements PrescriptionImagePicker {
  final ImagePicker _picker;

  DevicePrescriptionImagePicker({ImagePicker? picker})
    : _picker = picker ?? ImagePicker();

  @override
  Future<PickedPrescriptionImage?> pick(PrescriptionImageSource source) async {
    final file = await _picker.pickImage(
      source: source == PrescriptionImageSource.camera
          ? ImageSource.camera
          : ImageSource.gallery,
      imageQuality: 75,
    );
    return _read(file);
  }

  @override
  Future<PickedPrescriptionImage?> recoverLostImage() async {
    final response = await _picker.retrieveLostData();
    if (response.isEmpty) return null;

    final files = response.files;
    if (files == null || files.isEmpty) return null;
    return _read(files.first);
  }

  Future<PickedPrescriptionImage?> _read(XFile? file) async {
    if (file == null) return null;
    final bytes = await file.readAsBytes();
    if (bytes.isEmpty) return null;
    return PickedPrescriptionImage(bytes: bytes, name: file.name);
  }
}
