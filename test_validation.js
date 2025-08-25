#!/usr/bin/env node

// Simple validation script for the generated Playwright test
const fs = require('fs');
const path = require('path');

function validatePlaywrightTest(testFile) {
    console.log('🧪 Validating Playwright Test Structure');
    console.log('=' * 50);
    
    try {
        const content = fs.readFileSync(testFile, 'utf8');
        
        // Check for required imports
        const hasPlaywrightImport = content.includes("import { test, expect } from '@playwright/test'");
        console.log('✅ Playwright imports:', hasPlaywrightImport ? 'Present' : '❌ Missing');
        
        // Check for test structure
        const hasTestBlock = content.includes('test(');
        console.log('✅ Test block:', hasTestBlock ? 'Present' : '❌ Missing');
        
        // Check for navigation
        const hasNavigation = content.includes('page.goto');
        console.log('✅ Navigation:', hasNavigation ? 'Present' : '❌ Missing');
        
        // Check for login functionality
        const hasTokenLogin = content.includes('ABC123') || content.includes('Login with Token');
        console.log('✅ Token login:', hasTokenLogin ? 'Present' : '❌ Missing');
        
        // Check for chat functionality
        const hasChatQuery = content.includes('DM mail campaigns');
        console.log('✅ Chat query:', hasChatQuery ? 'Present' : '❌ Missing');
        
        // Check for assertions
        const hasAssertions = content.includes('expect(');
        console.log('✅ Assertions:', hasAssertions ? 'Present' : '❌ Missing');
        
        // Check for validation
        const hasValidation = content.includes('DM december 2018');
        console.log('✅ Response validation:', hasValidation ? 'Present' : '❌ Missing');
        
        // Count actions
        const actionCount = (content.match(/\/\/ Action:/g) || []).length;
        console.log('📊 Total actions:', actionCount);
        
        // Calculate test coverage
        const requiredElements = 7;
        const presentElements = [hasPlaywrightImport, hasTestBlock, hasNavigation, hasTokenLogin, hasChatQuery, hasAssertions, hasValidation].filter(Boolean).length;
        const coverage = Math.round((presentElements / requiredElements) * 100);
        
        console.log(`\n📈 Test Coverage: ${coverage}% (${presentElements}/${requiredElements})`);
        
        if (coverage >= 80) {
            console.log('🎉 Test validation: EXCELLENT');
        } else if (coverage >= 60) {
            console.log('✅ Test validation: GOOD');
        } else {
            console.log('⚠️  Test validation: NEEDS IMPROVEMENT');
        }
        
        return {
            valid: coverage >= 60,
            coverage: coverage,
            actionCount: actionCount,
            details: {
                hasPlaywrightImport,
                hasTestBlock,
                hasNavigation,
                hasTokenLogin,
                hasChatQuery,
                hasAssertions,
                hasValidation
            }
        };
        
    } catch (error) {
        console.error('❌ Error validating test:', error.message);
        return { valid: false, error: error.message };
    }
}

// Main execution
const testFile = path.join(__dirname, 'tests', 'afasask_critical_journey_test.js');
const result = validatePlaywrightTest(testFile);

console.log('\n🔍 Test Structure Analysis:');
console.log('File:', testFile);
console.log('Status:', result.valid ? '✅ Valid' : '❌ Invalid');

if (result.actionCount) {
    console.log(`Actions: ${result.actionCount} automated steps`);
}

console.log('\n📋 To run this test in a proper environment:');
console.log('1. npm install @playwright/test');
console.log('2. npx playwright install');
console.log('3. npx playwright test tests/afasask_critical_journey_test.js');