import 'package:go_router/go_router.dart';
import 'package:helm_marine/features/contractors/screens/contractor_inbox_screen.dart';
import 'package:helm_marine/features/contractors/screens/contractor_org_screen.dart';
import 'package:helm_marine/features/service_jobs/screens/new_service_job_screen.dart';
import 'package:helm_marine/features/service_jobs/screens/service_job_screen.dart';
import 'package:helm_marine/features/service_jobs/screens/service_jobs_list_screen.dart';

/// In-shell routes owned by the service-jobs workstream (owner and contractor journeys).
///
/// * `/service-jobs`, `/service-jobs/new?vessel_id=…&entry=vessel|first_mate`
/// * `/service-jobs/:id[/overview|capture|measurements|preparation|sharing|brief|scope|visits|feedback]`
/// * `/contractor/inbox`, `/contractor/organizations/:id`
/// * `/contractor/jobs/:id[/brief|requests|measurements|preparation|scope|visits|feedback]`
final List<RouteBase> serviceRoutes = <RouteBase>[
  GoRoute(
    path: '/service-jobs',
    builder: (context, state) => const ServiceJobsListScreen(),
    routes: [
      GoRoute(
        path: 'new',
        builder: (context, state) => NewServiceJobScreen(
          vesselId: state.uri.queryParameters['vessel_id'],
          entry: state.uri.queryParameters['entry'],
        ),
      ),
      GoRoute(
        path: ':jobId',
        builder: (context, state) => ServiceJobScreen(jobId: state.pathParameters['jobId']!),
        routes: [
          GoRoute(
            path: ':tab',
            builder: (context, state) =>
                ServiceJobScreen(jobId: state.pathParameters['jobId']!, tab: state.pathParameters['tab']),
          ),
        ],
      ),
    ],
  ),
  GoRoute(path: '/contractor/inbox', builder: (context, state) => const ContractorInboxScreen()),
  GoRoute(
    path: '/contractor/organizations/:orgId',
    builder: (context, state) => ContractorOrgScreen(orgId: state.pathParameters['orgId']!),
  ),
  GoRoute(
    path: '/contractor/jobs/:jobId',
    builder: (context, state) => ServiceJobScreen(jobId: state.pathParameters['jobId']!, contractor: true),
    routes: [
      GoRoute(
        path: ':tab',
        builder: (context, state) => ServiceJobScreen(
          jobId: state.pathParameters['jobId']!,
          tab: state.pathParameters['tab'],
          contractor: true,
        ),
      ),
    ],
  ),
];
