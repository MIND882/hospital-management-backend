import apiClient from './apiClient';

/**
 * Fetch main dashboard summary: upcoming appointments, stats, health tips
 * Backend: GET /api/dashboard/
 */
export const getDashboardData = async () => {
  const response = await apiClient.get('/dashboard/');
  return response.data;
};

/**
 * Fetch upcoming appointments for the logged-in patient
 * Backend: GET /api/appointments/?status=upcoming&limit=3
 */
export const getUpcomingAppointments = async () => {
  const response = await apiClient.get('/appointments/', {
    params: { status: 'upcoming', limit: 3 },
  });
  return response.data;
};

/**
 * Fetch recent lab bookings
 * Backend: GET /api/lab_tests/?limit=2
 */
export const getRecentLabBookings = async () => {
  const response = await apiClient.get('/lab_tests/', {
    params: { limit: 2 },
  });
  return response.data;
};

/**
 * Fetch recent pharmacy orders
 * Backend: GET /api/pharmacy/?limit=2
 */
export const getRecentOrders = async () => {
  const response = await apiClient.get('/pharmacy/', {
    params: { limit: 2 },
  });
  return response.data;
};

/**
 * Fetch user profile / greeting info
 * Backend: GET /api/profile/
 */
export const getUserProfile = async () => {
  const response = await apiClient.get('/profile/');
  return response.data;
};