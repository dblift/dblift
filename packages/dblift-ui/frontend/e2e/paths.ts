// Where the test server builds its fixture repositories. Under test-results/, which is ignored.
export const FIXTURES = new URL("../test-results/fixtures", import.meta.url).pathname;
