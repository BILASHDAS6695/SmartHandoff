export const environment = {
  production: true,
  apiBaseUrl: '',          // Same origin — served behind Cloud CDN
  idpBaseUrl: '#{IDP_BASE_URL}#',    // Token replaced by Cloud Build substitution
  oidcClientId: '#{OIDC_CLIENT_ID}#',
};
