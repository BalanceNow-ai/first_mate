import 'package:go_router/go_router.dart';
import 'package:helm_marine/features/invoices/contractor/contractor_invoice_questions_screen.dart';
import 'package:helm_marine/features/invoices/screens/invoice_detail_screen.dart';
import 'package:helm_marine/features/invoices/screens/invoice_list_screen.dart';
import 'package:helm_marine/features/invoices/screens/invoice_review_screen.dart';
import 'package:helm_marine/features/invoices/screens/invoice_upload_screen.dart';
import 'package:helm_marine/features/moderation/screens/moderation_screens.dart';

/// In-shell routes owned by the invoice / moderation client workstream:
/// "Understand my invoice" for owners, shared invoice questions for the
/// assigned contractor, and the case-scoped moderation console.
final List<RouteBase> invoiceRoutes = <RouteBase>[
  GoRoute(
    path: '/invoices',
    builder: (context, state) => const InvoiceListScreen(),
    routes: [
      GoRoute(
        path: 'new',
        builder: (context, state) => InvoiceUploadScreen(
          vesselId: state.uri.queryParameters['vessel_id'],
          jobId: state.uri.queryParameters['job_id'],
        ),
      ),
      GoRoute(
        path: ':invoiceId',
        builder: (context, state) => InvoiceDetailScreen(invoiceId: state.pathParameters['invoiceId']!),
        routes: [
          GoRoute(
            path: 'review',
            builder: (context, state) => InvoiceReviewScreen(
              invoiceId: state.pathParameters['invoiceId']!,
              initialSelection: state.uri.queryParameters['select'],
            ),
          ),
        ],
      ),
    ],
  ),
  GoRoute(
    path: '/contractor/jobs/:jobId/invoice-questions',
    builder: (context, state) => ContractorInvoiceQuestionsScreen(jobId: state.pathParameters['jobId']!),
  ),
  GoRoute(
    path: '/moderation',
    builder: (context, state) => const ModerationCasesScreen(),
    routes: [
      GoRoute(
        path: 'cases/:caseId',
        builder: (context, state) => ModerationCaseScreen(caseId: state.pathParameters['caseId']!),
      ),
    ],
  ),
];
