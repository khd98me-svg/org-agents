/**
 * Safety boundary for the organization-engine integration.
 *
 * OpenClawfice's bundled tickers target the separate OpenClaw runtime and can
 * dispatch work automatically. The organization bridge is read-only, so do not
 * start either legacy ticker until an explicit, reviewed integration exists.
 */
export async function register() {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    console.log('[openclawfice] Legacy OpenClaw autowork and watercooler tickers are disabled.');
  }
}
