export const environment = {
  production: false,
  apiBaseUrl: 'http://localhost:8000',
  idpBaseUrl: 'https://idp.hospital.example.com',   // Set in CI/CD env var injection
  oidcClientId: 'smarthandoff-api-gateway',           // Set in CI/CD env var injection
};
