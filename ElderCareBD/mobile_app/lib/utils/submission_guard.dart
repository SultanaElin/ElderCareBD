class SubmissionGuard {
  bool _isInProgress = false;

  bool get isInProgress => _isInProgress;

  bool tryStart() {
    if (_isInProgress) return false;
    _isInProgress = true;
    return true;
  }

  void finish() {
    _isInProgress = false;
  }
}
