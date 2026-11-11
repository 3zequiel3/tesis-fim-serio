import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

// Flat config (design D-13). Typed rules run on application code; test files
// get the non-typed recommended set because tsconfig.app.json excludes them.
const TESTS = ['src/**/*.test.{ts,tsx}', 'src/test/**/*.{ts,tsx}']

export default tseslint.config(
  { ignores: ['dist', 'coverage', 'playwright-report', 'test-results', 'docs'] },
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: TESTS,
    extends: [js.configs.recommended, ...tseslint.configs.recommendedTypeChecked],
    languageOptions: {
      globals: globals.browser,
      parserOptions: {
        project: './tsconfig.app.json',
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: { 'react-hooks': reactHooks, 'react-refresh': reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Event handlers may be async: React ignores the returned promise and the
      // handlers catch their own errors. Promise misuse elsewhere stays an error.
      '@typescript-eslint/no-misused-promises': ['error', { checksVoidReturn: { attributes: false } }],
      'react-refresh/only-export-components': ['error', { allowConstantExport: true }],
      // D-4: API errors are read through api/errors.ts only.
      'no-restricted-syntax': [
        'error',
        {
          selector: "MemberExpression[property.name='detail'][object.property.name='data']",
          message: 'Read API errors through readApiError()/apiErrorMessage() from api/errors.ts.',
        },
      ],
    },
  },
  {
    files: TESTS,
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { globals: { ...globals.browser, ...globals.vitest, ...globals.node } },
    plugins: { 'react-hooks': reactHooks },
    rules: { ...reactHooks.configs.recommended.rules },
  },
  {
    files: ['src/api/errors.ts'],
    rules: { 'no-restricted-syntax': 'off' },
  },
  {
    files: ['e2e/**/*.ts', '*.config.ts', 'vite*.ts'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },
)
