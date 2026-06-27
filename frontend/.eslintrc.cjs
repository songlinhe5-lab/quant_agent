module.exports = {
    root: true,
    env: {
        browser: true,
        node: true,
        es2021: true
    },
    extends: [
        'eslint:recommended',
        'plugin:@typescript-eslint/recommended',
        'plugin:vue/vue3-recommended',
        'prettier' // 必须放在最后，用于覆盖与 Prettier 冲突的规则
    ],
    parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        parser: '@typescript-eslint/parser'
    },
    rules: {
        'vue/multi-word-component-names': 'off', // 允许单单词组件名 (如 Dashboard.vue)
    }
}