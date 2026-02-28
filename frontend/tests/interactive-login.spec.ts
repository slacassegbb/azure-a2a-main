import { test, expect } from '@playwright/test';

test('Interactive login test', async ({ page }) => {
  // Navigate to your app
  await page.goto('http://localhost:3000');
  
  // Open login dialog - adjust selector based on your actual UI
  await page.click('button:has-text("Login"), button:has-text("Sign in"), [aria-label*="login" i], [aria-label*="user" i]');
  
  // Fill login form
  await page.fill('input[type="email"], input[name="email"]', 'test@example.com');
  await page.fill('input[type="password"], input[name="password"]', 'test123');
  
  // Click login button
  await page.click('button:has-text("Login")');
  
  // Wait to see what happens
  await page.waitForTimeout(3000);
  
  // Take a screenshot to see the result
  await page.screenshot({ path: 'login-result.png', fullPage: true });
});
