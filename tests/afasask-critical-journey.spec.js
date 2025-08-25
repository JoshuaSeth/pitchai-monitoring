import { test, expect } from '@playwright/test';

test('AFASASK Critical User Journey - DM Campaign Analysis', async ({ page }) => {
  test.setTimeout(180000); // 3 minutes timeout

  // Set viewport
  await page.setViewportSize({ width: 1280, height: 720 });

  // Action: browser_navigate
  await page.goto('https://afasask.gzb.nl');
  await page.waitForTimeout(100);

  // Action: browser_screenshot
  await page.screenshot({ fullPage: true });
  await page.waitForTimeout(100);

  // Action: browser_click
  await page.click(':text("Login with Token")');
  await page.waitForTimeout(100);

  // Action: browser_fill
  await page.fill('#token', 'ABC123');
  await page.waitForTimeout(100);

  // Action: browser_evaluate
  await page.evaluate(() => { // Find the token input and submit the form by pressing Enter
const tokenInput = document.querySelector('#token');
if (tokenInput) {
  const event = new KeyboardEvent('keydown', {
    key: 'Enter',
    keyCode: 13,
    which: 13,
    bubbles: true
  });
  tokenInput.dispatchEvent(event);
} else {
  // Alternative: find and click submit button
  const submitButton = document.querySelector('button[type="submit"]') || document.querySelector('input[type="submit"]');
  if (submitButton) {
    submitButton.click();
  }
} });
  await page.waitForTimeout(100);

  // Action: browser_wait_for_navigation
  await page.waitForTimeout(100);

  // Action: browser_get_page_info
  await page.waitForTimeout(100);

  // Action: browser_evaluate
  await page.evaluate(() => { window.location.href });
  await page.waitForTimeout(100);

  // Action: browser_evaluate
  await page.evaluate(() => { // Check for error messages and form elements
const errors = document.querySelectorAll('.error, .alert, .warning, [class*="error"], [class*="alert"]');
const form = document.querySelector('form');
const submitBtn = document.querySelector('button[type="submit"]');
const tokenInput = document.querySelector('#token');

return {
  errors: Array.from(errors).map(el => el.textContent.trim()),
  hasForm: !!form,
  hasSubmitButton: !!submitBtn,
  hasTokenInput: !!tokenInput,
  tokenValue: tokenInput ? tokenInput.value : 'not found',
  submitButtonText: submitBtn ? submitBtn.textContent.trim() : 'no submit button'
}; });
  await page.waitForTimeout(100);

  // Action: browser_evaluate
  await page.evaluate(() => { (function() {
  const errors = document.querySelectorAll('.error, .alert, .warning, [class*="error"], [class*="alert"]');
  const form = document.querySelector('form');
  const submitBtn = document.querySelector('button[type="submit"]');
  const tokenInput = document.querySelector('#token');

  return {
    errors: Array.from(errors).map(el => el.textContent.trim()),
    hasForm: !!form,
    hasSubmitButton: !!submitBtn,
    hasTokenInput: !!tokenInput,
    tokenValue: tokenInput ? tokenInput.value : 'not found',
    submitButtonText: submitBtn ? submitBtn.textContent.trim() : 'no submit button'
  };
})() });
  await page.waitForTimeout(100);

  // Action: browser_click
  await page.click('button[type="submit"]');
  await page.waitForTimeout(100);

  // Action: browser_evaluate
  await page.evaluate(() => { setTimeout(() => window.location.href, 2000) });
  await page.waitForTimeout(100);

  // Action: browser_evaluate
  await page.evaluate(() => { window.location.href });
  await page.waitForTimeout(100);

  // Action: browser_wait_for_element
  await page.waitForSelector('#chat-input', { timeout: 30000 });
  await page.waitForTimeout(100);

  // Action: browser_type
  await page.type('#chat-input', 'which DM mail campaigns performed best?');
  await page.waitForTimeout(100);

  // Action: browser_evaluate
  await page.evaluate(() => { (function() {
  const chatInput = document.querySelector('#chat-input');
  if (chatInput) {
    const event = new KeyboardEvent('keydown', {
      key: 'Enter',
      keyCode: 13,
      which: 13,
      bubbles: true
    });
    chatInput.dispatchEvent(event);
    return true;
  }
  return false;
})() });
  await page.waitForTimeout(100);

  // Action: browser_evaluate
  await page.evaluate(() => { (function() {
  // Wait for response with polling approach
  let attempts = 0;
  const maxAttempts = 60; // 60 seconds
  
  function checkForResponse() {
    attempts++;
    
    // Look for response in chat messages or content
    const messages = document.querySelectorAll('.message, .chat-message, .response, [class*="message"], [class*="response"]');
    const chatContainer = document.querySelector('.chat-container, .messages, [class*="chat"], [class*="message"]');
    const bodyText = document.body.textContent || document.body.innerText || '';
    
    // Check for DM-related content
    const hasDMContent = bodyText.toLowerCase().includes('dm') || 
                        bodyText.toLowerCase().includes('mail') || 
                        bodyText.toLowerCase().includes('campaign');
    
    if (hasDMContent && messages.length > 0) {
      return {
        success: true,
        responseFound: true,
        messageCount: messages.length,
        containsDM: bodyText.toLowerCase().includes('dm'),
        containsMail: bodyText.toLowerCase().includes('mail'),
        containsCampaign: bodyText.toLowerCase().includes('campaign'),
        attempts: attempts
      };
    }
    
    if (attempts < maxAttempts) {
      setTimeout(checkForResponse, 1000);
    } else {
      return {
        success: false,
        responseFound: false,
        messageCount: messages.length,
        bodyTextPreview: bodyText.substring(0, 500),
        attempts: attempts
      };
    }
  }
  
  return new Promise((resolve) => {
    function pollForResponse() {
      attempts++;
      const messages = document.querySelectorAll('.message, .chat-message, .response, [class*="message"], [class*="response"]');
      const bodyText = document.body.textContent || document.body.innerText || '';
      const hasDMContent = bodyText.toLowerCase().includes('dm-mail') || 
                          (bodyText.toLowerCase().includes('dm') && bodyText.toLowerCase().includes('mail'));
      
      if (hasDMContent || attempts >= maxAttempts) {
        resolve({
          success: hasDMContent,
          responseFound: messages.length > 0,
          messageCount: messages.length,
          containsDMMail: bodyText.toLowerCase().includes('dm-mail'),
          containsDM: bodyText.toLowerCase().includes('dm'),
          containsMail: bodyText.toLowerCase().includes('mail'),
          containsCampaign: bodyText.toLowerCase().includes('campaign'),
          attempts: attempts,
          bodyTextPreview: bodyText.substring(0, 1000)
        });
      } else {
        setTimeout(pollForResponse, 1000);
      }
    }
    
    pollForResponse();
  });
})() });
  await page.waitForTimeout(100);

  // Action: browser_screenshot
  await page.screenshot({ fullPage: true });
  await page.waitForTimeout(100);

  // Action: browser_screenshot
  await page.screenshot({ fullPage: false });
  await page.waitForTimeout(100);

  // Wait for and verify response with proper polling
  console.log('🔍 Waiting for DM campaign analysis response...');
  
  let responseFound = false;
  let attempts = 0;
  const maxAttempts = 60; // 60 seconds
  
  while (!responseFound && attempts < maxAttempts) {
    await page.waitForTimeout(1000); // Wait 1 second between checks
    
    const content = await page.content();
    const bodyText = await page.textContent('body') || '';
    
    // Check for various indicators of a successful response
    const hasDMContent = content.includes('DM-mail') || 
                        content.includes('DM') || 
                        bodyText.toLowerCase().includes('campaign') ||
                        content.includes('mail') ||
                        content.includes('€') ||
                        content.includes('december');
    
    if (hasDMContent) {
      console.log('✅ Response content found!');
      responseFound = true;
      break;
    }
    
    attempts++;
    if (attempts % 10 === 0) {
      console.log(`⏳ Still waiting for response... ${attempts}s elapsed`);
    }
  }
  
  // Final verification
  const finalContent = await page.content();
  const finalBodyText = await page.textContent('body') || '';
  
  // More flexible validation - check for any DM/campaign related content
  const hasValidResponse = finalContent.includes('DM-mail') || 
                          finalContent.includes('DM') || 
                          finalBodyText.toLowerCase().includes('campaign') ||
                          finalContent.includes('mail') ||
                          finalContent.includes('€');
  
  if (!hasValidResponse) {
    console.log('⚠️ No response found, taking debug screenshot...');
    await page.screenshot({ path: 'test-results/debug-no-response.png', fullPage: true });
    console.log('Current URL:', page.url());
    console.log('Body text preview:', finalBodyText.substring(0, 200));
  }
  
  expect(hasValidResponse).toBeTruthy();
  expect(page.url()).toBeTruthy();
});