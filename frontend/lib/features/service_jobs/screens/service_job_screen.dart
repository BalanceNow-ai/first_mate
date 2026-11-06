import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:helm_marine/core/theme/helm_theme.dart';
import 'package:helm_marine/core/widgets/state_views.dart';
import 'package:helm_marine/features/service_jobs/data/labels.dart';
import 'package:helm_marine/features/service_jobs/data/service_job_models.dart';
import 'package:helm_marine/features/service_jobs/providers/service_jobs_providers.dart';
import 'package:helm_marine/features/service_jobs/tabs/brief_tab.dart';
import 'package:helm_marine/features/service_jobs/tabs/capture_tab.dart';
import 'package:helm_marine/features/service_jobs/tabs/feedback_tab.dart';
import 'package:helm_marine/features/service_jobs/tabs/measurements_tab.dart';
import 'package:helm_marine/features/service_jobs/tabs/overview_tab.dart';
import 'package:helm_marine/features/service_jobs/tabs/preparation_tab.dart';
import 'package:helm_marine/features/service_jobs/tabs/requests_tab.dart';
import 'package:helm_marine/features/service_jobs/tabs/scope_tab.dart';
import 'package:helm_marine/features/service_jobs/tabs/sharing_tab.dart';
import 'package:helm_marine/features/service_jobs/tabs/visits_tab.dart';
import 'package:helm_marine/features/service_jobs/widgets/common.dart';

/// One tab of a job workspace: its route segment, label and (contractor) section.
class JobTab {
  const JobTab(this.segment, this.label, this.icon, {this.section});

  final String segment;
  final String label;
  final IconData icon;
  final String? section;
}

const ownerTabs = [
  JobTab('overview', 'Overview', Icons.dashboard_outlined),
  JobTab('capture', 'Capture', Icons.photo_camera_outlined),
  JobTab('measurements', 'Measurements', Icons.straighten),
  JobTab('preparation', 'Preparation', Icons.inventory_2_outlined),
  JobTab('sharing', 'Sharing', Icons.share_outlined),
  JobTab('brief', 'Brief', Icons.description_outlined),
  JobTab('scope', 'Scope', Icons.assignment_turned_in_outlined),
  JobTab('visits', 'Visits', Icons.event_available_outlined),
  JobTab('feedback', 'Feedback', Icons.rate_review_outlined),
];

const contractorTabs = [
  JobTab('brief', 'Brief', Icons.description_outlined, section: 'preparation'),
  JobTab('requests', 'Requests', Icons.photo_library_outlined, section: 'evidence'),
  JobTab('measurements', 'Measurements', Icons.straighten, section: 'measurements'),
  JobTab('preparation', 'Preparation', Icons.inventory_2_outlined, section: 'preparation'),
  JobTab('scope', 'Scope', Icons.assignment_turned_in_outlined, section: 'scope'),
  JobTab('visits', 'Visits', Icons.event_available_outlined),
  JobTab('feedback', 'Feedback', Icons.rate_review_outlined),
];

/// `/service-jobs/:id[/tab]` (owner) and `/contractor/jobs/:id[/tab]` (assigned contractor).
class ServiceJobScreen extends ConsumerWidget {
  const ServiceJobScreen({super.key, required this.jobId, this.tab, this.contractor = false});

  final String jobId;
  final String? tab;
  final bool contractor;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final job = ref.watch(serviceJobProvider(jobId));
    return job.when(
      loading: () => Scaffold(appBar: AppBar(title: const Text('Service job')), body: const LoadingView(message: 'Loading job')),
      error: (e, _) => Scaffold(
        appBar: AppBar(title: const Text('Service job')),
        body: ErrorView(error: e, title: friendlyTitle(e), onRetry: () => ref.invalidate(serviceJobProvider(jobId))),
      ),
      data: (j) => _Workspace(job: j, tab: tab, contractor: contractor),
    );
  }
}

class _Workspace extends ConsumerWidget {
  const _Workspace({required this.job, required this.tab, required this.contractor});

  final ServiceJob job;
  final String? tab;
  final bool contractor;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Someone who opens the owner URL while assigned sees the contractor workspace (and vice versa).
    final asContractor = contractor || !job.viewer.isOwner;
    final tabs = asContractor
        ? [for (final t in contractorTabs) if (t.section == null || job.viewer.can(t.section!)) t]
        : ownerTabs;
    final index = tabs.indexWhere((t) => t.segment == tab);
    final base = asContractor ? '/contractor/jobs/${job.id}' : '/service-jobs/${job.id}';
    return DefaultTabController(
      key: ValueKey('${job.id}-$tab'),
      length: tabs.length,
      initialIndex: index < 0 ? 0 : index,
      child: Scaffold(
        appBar: AppBar(
          title: Text(job.title, overflow: TextOverflow.ellipsis),
          leading: IconButton(
            icon: const Icon(Icons.arrow_back),
            tooltip: asContractor ? 'Back to contractor inbox' : 'Back to service jobs',
            onPressed: () => context.go(asContractor ? '/contractor/inbox' : '/service-jobs'),
          ),
          actions: [
            IconButton(
              icon: const Icon(Icons.refresh),
              tooltip: 'Reload',
              onPressed: () => refreshServiceJob(ref, job.id),
            ),
          ],
          bottom: TabBar(
            isScrollable: true,
            tabAlignment: TabAlignment.start,
            labelColor: Colors.white,
            unselectedLabelColor: Colors.white70,
            indicatorColor: HelmTheme.seafoam,
            onTap: (i) => GoRouter.of(context).replace('$base/${tabs[i].segment}'),
            tabs: [for (final t in tabs) Tab(icon: Icon(t.icon, size: 20), text: t.label)],
          ),
        ),
        body: Column(children: [
          if (asContractor) SnapshotBanner(job: job),
          Expanded(
            child: TabBarView(
              children: [for (final t in tabs) _tabBody(t.segment, asContractor)],
            ),
          ),
        ]),
      ),
    );
  }

  Widget _tabBody(String segment, bool asContractor) {
    final child = switch (segment) {
      'overview' => OverviewTab(job: job),
      'capture' => CaptureTab(job: job),
      'requests' => RequestsTab(job: job),
      'measurements' => MeasurementsTab(job: job),
      'preparation' => PreparationTab(job: job),
      'sharing' => SharingTab(job: job),
      'brief' => asContractor ? ContractorBriefTab(job: job) : BriefTab(job: job),
      'scope' => ScopeTab(job: job),
      'visits' => VisitsTab(job: job),
      'feedback' => FeedbackTab(job: job),
      _ => const SizedBox.shrink(),
    };
    return ContentWidth(maxWidth: 960, child: child);
  }
}

/// Contractor: where the job content comes from — the published brief (live updates
/// off), nothing yet (no brief published) or live.
class SnapshotBanner extends StatelessWidget {
  const SnapshotBanner({super.key, required this.job});

  final ServiceJob job;

  @override
  Widget build(BuildContext context) {
    final (text, tone, icon) = switch (job.snapshotState) {
      'no_brief_published' => (
          "The owner hasn't published a brief yet. Until they do you see only the job's title and status — "
              'evidence requests, scope, visits and invoice questions still work.',
          Tone.warn,
          Icons.hourglass_empty,
        ),
      'brief' => (
          'Showing the brief published on '
              '${job.snapshotPublishedAt == null ? 'an earlier date' : formatDate(job.snapshotPublishedAt!)}. '
              'Changes the owner makes later appear when they publish a new brief.',
          Tone.info,
          Icons.description_outlined,
        ),
      'live' => ('Live: you see the shared sections as they are now.', Tone.good, Icons.sync),
      _ => (null, Tone.neutral, Icons.info_outline),
    };
    if (text == null) return const SizedBox.shrink();
    return Semantics(
      container: true,
      child: ContentWidth(
        maxWidth: 960,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
          child: InfoNote(text, tone: tone, icon: icon),
        ),
      ),
    );
  }
}
