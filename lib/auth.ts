/**
 * Initiates the Riot OAuth flow
 */
export const initiateRiotOAuth = async () => {
  try {
    const response = await fetch('/api/auth/riot', {
      redirect: 'follow',
    });

    // The server will redirect, but we need to redirect the user manually in the client
    window.location.href = '/api/auth/riot';
  } catch (error) {
    console.error('Failed to initiate OAuth:', error);
    throw new Error('Failed to initiate authentication');
  }
};

/**
 * Gets the current user from cookies
 */
export const getCurrentUser = () => {
  if (typeof window === 'undefined') return null;

  const userCookie = document.cookie
    .split('; ')
    .find((row) => row.startsWith('user_info='));

  if (!userCookie) return null;

  try {
    const userJson = userCookie.split('=')[1];
    return JSON.parse(decodeURIComponent(userJson));
  } catch {
    return null;
  }
};

/**
 * Logs out the user
 */
export const logout = async () => {
  // Clear auth cookies
  document.cookie = 'auth_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 UTC;';
  document.cookie = 'user_info=; path=/; expires=Thu, 01 Jan 1970 00:00:00 UTC;';

  // Redirect to home
  window.location.href = '/';
};
