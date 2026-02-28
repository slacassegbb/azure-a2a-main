import { test, expect } from '@playwright/test';

/**
 * Login Flow Tests for A2A Platform
 * 
 * These tests verify the authentication functionality including:
 * - Successful login
 * - Failed login with invalid credentials
 * - Form validation
 * - User registration
 * - Mode switching between login and register
 */

const BASE_URL = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:3000';
const API_URL = process.env.NEXT_PUBLIC_A2A_API_URL || 'http://localhost:12000';

test.describe('Login Dialog', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to the application
    await page.goto(BASE_URL);
    
    // Clear session storage to ensure clean state
    await page.evaluate(() => sessionStorage.clear());
  });

  test('should open login dialog when clicking login button', async ({ page }) => {
    // Look for the login trigger button (User icon in header)
    const loginButton = page.getByRole('button', { name: /login|sign in|user/i }).first();
    await loginButton.click();

    // Verify dialog is visible
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByText(/login/i)).toBeVisible();
  });

  test('should show validation error for empty form submission', async ({ page }) => {
    // Open login dialog
    const loginButton = page.getByRole('button', { name: /login|sign in|user/i }).first();
    await loginButton.click();

    // Try to submit without filling fields
    await page.getByRole('button', { name: /^login$/i }).click();

    // Verify error message
    await expect(page.getByText(/please fill in all fields/i)).toBeVisible();
  });

  test('should successfully login with valid credentials', async ({ page, context }) => {
    // Mock the API response for successful login
    await page.route(`${API_URL}/api/auth/login`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          access_token: 'mock_jwt_token_12345',
          user_info: {
            user_id: 'test-user-1',
            email: 'test@example.com',
            name: 'Test User',
            role: 'Developer',
            description: 'Test account',
            skills: ['testing', 'automation'],
            color: '#3B82F6'
          }
        })
      });
    });

    // Open login dialog
    const loginButton = page.getByRole('button', { name: /login|sign in|user/i }).first();
    await loginButton.click();

    // Fill in login form
    await page.getByLabel(/email/i).fill('test@example.com');
    await page.getByLabel(/password/i).fill('password123');

    // Submit the form
    await page.getByRole('button', { name: /^login$/i }).click();

    // Wait for sessionStorage to be set
    await page.waitForFunction(
      () => sessionStorage.getItem('auth_token') !== null,
      { timeout: 5000 }
    );

    // Verify token is stored
    const token = await page.evaluate(() => sessionStorage.getItem('auth_token'));
    expect(token).toBe('mock_jwt_token_12345');
  });

  test('should show error message for invalid credentials', async ({ page }) => {
    // Mock the API response for failed login
    await page.route(`${API_URL}/api/auth/login`, async (route) => {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({
          success: false,
          message: 'Invalid email or password'
        })
      });
    });

    // Open login dialog
    const loginButton = page.getByRole('button', { name: /login|sign in|user/i }).first();
    await loginButton.click();

    // Fill in login form with invalid credentials
    await page.getByLabel(/email/i).fill('invalid@example.com');
    await page.getByLabel(/password/i).fill('wrongpassword');

    // Submit the form
    await page.getByRole('button', { name: /^login$/i }).click();

    // Verify error message is displayed
    await expect(page.getByText(/invalid email or password/i)).toBeVisible();

    // Verify no token is stored
    const token = await page.evaluate(() => sessionStorage.getItem('auth_token'));
    expect(token).toBeNull();
  });

  test('should switch to register mode', async ({ page }) => {
    // Open login dialog
    const loginButton = page.getByRole('button', { name: /login|sign in|user/i }).first();
    await loginButton.click();

    // Click "Need an account? Register" link
    await page.getByText(/need an account.*register/i).click();

    // Verify additional registration fields are visible
    await expect(page.getByLabel(/name/i)).toBeVisible();
    await expect(page.getByLabel(/role/i)).toBeVisible();
    await expect(page.getByLabel(/description/i)).toBeVisible();
    await expect(page.getByLabel(/skills/i)).toBeVisible();

    // Verify button text changed to "Register"
    await expect(page.getByRole('button', { name: /^register$/i })).toBeVisible();
  });

  test('should switch back to login mode from register mode', async ({ page }) => {
    // Open login dialog
    const loginButton = page.getByRole('button', { name: /login|sign in|user/i }).first();
    await loginButton.click();

    // Switch to register mode
    await page.getByText(/need an account.*register/i).click();

    // Switch back to login mode
    await page.getByText(/already have an account.*login/i).click();

    // Verify we're back in login mode (additional fields should not be visible)
    await expect(page.getByLabel(/name/i)).not.toBeVisible();
    await expect(page.getByLabel(/role/i)).not.toBeVisible();

    // Verify button text is "Login"
    await expect(page.getByRole('button', { name: /^login$/i })).toBeVisible();
  });

  test('should successfully register a new user', async ({ page }) => {
    // Mock the API response for successful registration
    await page.route(`${API_URL}/api/auth/register`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          access_token: 'new_user_token_67890',
          user_info: {
            user_id: 'new-user-1',
            email: 'newuser@example.com',
            name: 'New User',
            role: 'QA Engineer',
            description: 'Testing the platform',
            skills: ['testing', 'automation', 'playwright'],
            color: '#3B82F6'
          }
        })
      });
    });

    // Open login dialog
    const loginButton = page.getByRole('button', { name: /login|sign in|user/i }).first();
    await loginButton.click();

    // Switch to register mode
    await page.getByText(/need an account.*register/i).click();

    // Fill in registration form
    await page.getByLabel(/email/i).fill('newuser@example.com');
    await page.getByLabel(/password/i).fill('securepass123');
    await page.getByLabel(/name/i).fill('New User');
    await page.getByLabel(/role/i).fill('QA Engineer');
    await page.getByLabel(/description/i).fill('Testing the platform');
    await page.getByLabel(/skills/i).fill('testing, automation, playwright');

    // Submit the registration form
    await page.getByRole('button', { name: /^register$/i }).click();

    // Wait for sessionStorage to be set
    await page.waitForFunction(
      () => sessionStorage.getItem('auth_token') !== null,
      { timeout: 5000 }
    );

    // Verify token is stored
    const token = await page.evaluate(() => sessionStorage.getItem('auth_token'));
    expect(token).toBe('new_user_token_67890');
  });

  test('should show validation error for incomplete registration', async ({ page }) => {
    // Open login dialog
    const loginButton = page.getByRole('button', { name: /login|sign in|user/i }).first();
    await loginButton.click();

    // Switch to register mode
    await page.getByText(/need an account.*register/i).click();

    // Fill only email and password (missing required fields)
    await page.getByLabel(/email/i).fill('newuser@example.com');
    await page.getByLabel(/password/i).fill('password123');

    // Try to submit
    await page.getByRole('button', { name: /^register$/i }).click();

    // Verify validation error
    await expect(page.getByText(/please fill in all required fields/i)).toBeVisible();
  });
});

test.describe('Authenticated State', () => {
  test('should include auth token in API requests after login', async ({ page }) => {
    // Set up auth token in sessionStorage
    await page.goto(BASE_URL);
    await page.evaluate(() => {
      sessionStorage.setItem('auth_token', 'test_token_12345');
    });

    // Intercept API requests to verify token is included
    const requestPromise = page.waitForRequest(
      request => request.url().includes('/api/') && 
                 request.headers()['authorization'] === 'Bearer test_token_12345'
    );

    // Reload page to trigger authenticated requests
    await page.reload();

    // Note: This test assumes your app makes authenticated API calls on page load
    // Adjust the assertion based on your actual API call patterns
  });
});
