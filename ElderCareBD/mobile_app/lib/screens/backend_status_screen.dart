import 'package:flutter/material.dart';

import '../services/api_service.dart';
import '../utils/app_colors.dart';
import '../widgets/app_card.dart';
import '../widgets/responsive_content.dart';

class BackendStatusScreen extends StatefulWidget {
  const BackendStatusScreen({super.key});

  @override
  State<BackendStatusScreen> createState() => _BackendStatusScreenState();
}

class _BackendStatusScreenState extends State<BackendStatusScreen> {
  bool isLoading = true;
  bool isConnected = false;

  @override
  void initState() {
    super.initState();
    _checkConnection();
  }

  Future<void> _checkConnection() async {
    final result = await ApiService.checkBackendConnection();

    if (!mounted) return;

    setState(() {
      isConnected = result;
      isLoading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final color = isConnected ? AppColors.green : AppColors.red;

    return Scaffold(
      appBar: AppBar(title: const Text('Backend Status')),
      body: ResponsiveContent(
        maxWidth: 620,
        child: Center(
          child: AppCard(
            padding: const EdgeInsets.all(28),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (isLoading)
                  Semantics(
                    label: 'Checking backend connection',
                    liveRegion: true,
                    child: const CircularProgressIndicator(),
                  )
                else
                  CircleAvatar(
                    radius: 42,
                    backgroundColor: color.withValues(alpha: 0.12),
                    child: Icon(
                      isConnected
                          ? Icons.cloud_done_rounded
                          : Icons.cloud_off_rounded,
                      color: color,
                      size: 52,
                    ),
                  ),
                const SizedBox(height: 20),
                Text(
                  isLoading
                      ? 'Checking backend...'
                      : isConnected
                      ? 'Backend Connected'
                      : 'Backend Not Connected',
                  style: TextStyle(
                    fontSize: 24,
                    fontWeight: FontWeight.w900,
                    color: color,
                  ),
                ),
                const SizedBox(height: 10),
                Text(
                  isConnected
                      ? 'Flutter app can communicate with FastAPI backend.'
                      : 'Could not connect to the configured FastAPI backend. Check the server and network, then retry.',
                  textAlign: TextAlign.center,
                  style: TextStyle(height: 1.5, color: Colors.black54),
                ),
                const SizedBox(height: 20),
                OutlinedButton.icon(
                  onPressed: () {
                    setState(() {
                      isLoading = true;
                    });
                    _checkConnection();
                  },
                  icon: const Icon(Icons.refresh_rounded),
                  label: const Text('Check Again'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
