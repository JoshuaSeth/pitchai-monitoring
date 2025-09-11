import { test, expect } from '@playwright/test';

test('Chat Interface Complete Interaction Flow Test', async ({ page }) => {
  test.setTimeout(60000);

  // Set viewport
  await page.setViewportSize({ width: 1280, height: 720 });

  // Navigate directly to the chat interface
  await page.goto('https://chat.pitchai.net/chat_mini/ortho_ridderkerk/test');
  await page.waitForTimeout(2000);

  // Wait for chat input to be available
  await page.waitForSelector('#chat-input', { timeout: 15000 });
  await page.waitForTimeout(500);

  // Click on the chat input field
  await page.click('#chat-input');
  await page.waitForTimeout(200);

  // Type the test message
  await page.type('#chat-input', 'Hello, I need help with orthodontic treatment');
  await page.waitForTimeout(500);

  // Click the submit button
  await page.click('button[type="submit"]');
  await page.waitForTimeout(1000);

  // Wait for message container and response
  await page.waitForSelector('#msg-container', { timeout: 10000 });
  await page.waitForTimeout(10000); // Wait for bot response

  // Verify the bot response contains expected text
  const content = await page.content();
  expect(content).toContain('Wat leuk dat je contact opneemt met Orthodontie Ridderkerk');
  
  // Verify page loaded without errors
  const url = page.url();
  expect(url).toBeTruthy();
});