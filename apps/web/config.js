/* Runtime configuration.
 *
 * Overwritten at deploy time by scripts/deploy.py with the real API URL. The
 * default is same-origin, which is what the local dev server serves, so the app
 * works out of the box with no configuration.
 *
 * Nothing secret belongs here: this file is served to every visitor.
 */
window.SCADS_CONFIG = {
  apiBaseUrl: "",
  environment: "local",
  build: "dev"
};
