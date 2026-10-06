// 화면 주소를 한곳에서 만든다.
export const routes = {
  home: (tenant: string) => `/${tenant}`,
  library: (tenant: string, system: string) => `/${tenant}/s/${system}`,
  document: (tenant: string, system: string, documentId: string) =>
    `/${tenant}/s/${system}/docs/${documentId}`,
  build: (tenant: string, system: string) => `/${tenant}/s/${system}/build`,
  coverage: (tenant: string, system: string) => `/${tenant}/s/${system}/coverage`,
  records: (tenant: string, system: string) => `/${tenant}/s/${system}/records`,
  artifact: (tenant: string, system: string, artifactId: string) =>
    `/${tenant}/s/${system}/records/${artifactId}`,
  decisions: (tenant: string, system: string, query?: string) =>
    `/${tenant}/s/${system}/decisions${query ? `?q=${encodeURIComponent(query)}` : ""}`,
  sources: (tenant: string) => `/${tenant}/sources`,
  source: (tenant: string, sourceId: string) => `/${tenant}/sources/${sourceId}`,
  org: (tenant: string) => `/${tenant}/org`,
  members: (tenant: string) => `/${tenant}/members`,
  audit: (tenant: string) => `/${tenant}/audit`,
  settings: (tenant: string) => `/${tenant}/settings`,
};
