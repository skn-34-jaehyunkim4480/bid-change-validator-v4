/** Case-scoped screens must be opened with a case ID. */
export type CaseDestination = 'qualification' | 'changes';

export function caseDestinationHref(caseId: string, destination: CaseDestination = 'qualification') {
  return '/' + destination + '?caseId=' + encodeURIComponent(caseId);
}

export function hasNoticeChangeVersion(versions: ReadonlyArray<{ version_number: number }>) {
  return new Set(versions.map((version) => version.version_number)).size > 1;
}
