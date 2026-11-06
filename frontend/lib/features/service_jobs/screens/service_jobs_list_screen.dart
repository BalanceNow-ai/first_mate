import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:helm_marine/core/api/paged.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/contractors/providers/contractor_providers.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';
import 'package:helm_marine/features/service_jobs/providers/service_jobs_providers.dart';
import 'package:helm_marine/features/service_jobs/widgets/common.dart';

/// `/service-jobs`: the owner's service jobs (drafts resume where they were left).
class ServiceJobsListScreen extends ConsumerWidget {
  const ServiceJobsListScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final jobs = ref.watch(serviceJobListProvider);
    final memberships = ref.watch(myMembershipsProvider).value ?? const [];
    return Scaffold(
      appBar: AppBar(
        title: const Text('Service jobs'),
        actions: [
          if (memberships.isNotEmpty)
            TextButton.icon(
              style: TextButton.styleFrom(foregroundColor: Colors.white),
              onPressed: () => context.go('/contractor/inbox'),
              icon: const Icon(Icons.inbox_outlined),
              label: const Text('Contractor inbox'),
            ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => context.go('/service-jobs/new?entry=service'),
        icon: const Icon(Icons.add),
        label: const Text('New service job'),
      ),
      body: jobs.when(
        loading: () => const LoadingView(message: 'Loading service jobs'),
        error: (e, _) => ErrorView(
          error: e,
          title: 'Could not load your service jobs',
          onRetry: () => ref.invalidate(serviceJobListProvider),
        ),
        data: (page) => RefreshIndicator(
          onRefresh: () => ref.refresh(serviceJobListProvider.future),
          child: ContentWidth(
            maxWidth: 900,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 96),
              children: [
                const InfoNote(
                  'Describe a problem, collect useful photos and measurements, and share a brief with a '
                  'contractor you choose. Drafts are saved as you go — open one to carry on.',
                ),
                if (page.items.isEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 32),
                    child: Column(
                      children: [
                        const Icon(Icons.build_circle_outlined, size: 56, color: HelmTheme.mutedText),
                        const SizedBox(height: 12),
                        const Text('No service jobs yet', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
                        const SizedBox(height: 8),
                        const Text('Start one from a vessel with “Get help with a problem”.', textAlign: TextAlign.center),
                        const SizedBox(height: 16),
                        ActionButton(
                          label: 'Choose a vessel',
                          icon: Icons.directions_boat,
                          onPressed: () => context.go('/vessels'),
                        ),
                      ],
                    ),
                  ),
                for (final job in page.items) _JobCard(job: job),
                LoadMoreButton(
                  hasMore: page.hasMore,
                  loadingMore: page.loadingMore,
                  error: page.moreError,
                  label: 'Load more jobs',
                  onLoadMore: () => ref.read(serviceJobListProvider.notifier).loadMore(),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _JobCard extends StatelessWidget {
  const _JobCard({required this.job});

  final JobListItem job;

  @override
  Widget build(BuildContext context) {
    final facts = [
      if (job.outstandingRequests > 0)
        '${job.outstandingRequests} request${job.outstandingRequests == 1 ? '' : 's'} still needed',
      if (job.gapCount > 0) '${job.gapCount} gap${job.gapCount == 1 ? '' : 's'} recorded',
      if (job.assignmentStatus != null) 'Contractor: ${assignmentStatusLabel(job.assignmentStatus).toLowerCase()}',
      'Updated ${formatDateTime(job.updatedAt)}',
    ];
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: InkWell(
        onTap: () => context.go('/service-jobs/${job.id}'),
        child: Semantics(
          button: true,
          label: 'Open service job ${job.title}, ${jobStatusLabel(job.status)}',
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(job.title,
                          style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
                    ),
                    const Icon(Icons.chevron_right),
                  ],
                ),
                const SizedBox(height: 8),
                Wrap(spacing: 8, runSpacing: 8, children: [
                  StatusBadge(jobStatusLabel(job.status), tone: jobStatusTone(job.status), semanticPrefix: 'Status'),
                  StatusBadge('Urgency: ${urgencyLabel(job.urgency)}'),
                ]),
                const SizedBox(height: 8),
                Text(facts.join(' · '), style: const TextStyle(color: HelmTheme.mutedText)),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
