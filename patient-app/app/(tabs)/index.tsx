import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  StyleSheet,
  RefreshControl,
  ActivityIndicator,
  Alert,
  Platform,
  StatusBar,
} from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons, MaterialCommunityIcons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { useSelector } from 'react-redux';
import {
  getDashboardData,
  getUpcomingAppointments,
  getUserProfile,
  getRecentLabBookings,
  getRecentOrders,
} from '../../src/services/dashboardService';

// ─── Theme ───────────────────────────────────────────────────────────────────
const C = {
  primary: '#0A5F55',
  primaryLight: '#12897A',
  primaryPale: '#E8F5F3',
  accent: '#FF6B35',
  accentLight: '#FFF0EB',
  emergency: '#E63946',
  emergencyLight: '#FDECEA',
  warning: '#F4A261',
  blue: '#2196F3',
  blueLight: '#E3F2FD',
  purple: '#7B2FBE',
  purpleLight: '#F0E6FF',
  bg: '#F0F4F8',
  card: '#FFFFFF',
  text: '#1A2332',
  textSecondary: '#6B7B8D',
  textMuted: '#A0ADB8',
  border: '#E8ECF0',
  shadow: '#000',
};

// ─── Quick Services Data ──────────────────────────────────────────────────────
const QUICK_SERVICES = [
  {
    id: 'doctor',
    label: 'Book\nDoctor',
    icon: 'stethoscope',
    iconLib: 'mci',
    color: C.primary,
    bg: C.primaryPale,
    route: '/features/doctor/screens/DoctorCategoriesScreen',
  },
  {
    id: 'lab',
    label: 'Lab\nTests',
    icon: 'flask-outline',
    iconLib: 'ion',
    color: C.blue,
    bg: C.blueLight,
    route: '/features/lab/screens/LabTestCategoriesScreen',
  },
  {
    id: 'pharmacy',
    label: 'Order\nMedicine',
    icon: 'medkit-outline',
    iconLib: 'ion',
    color: C.purple,
    bg: C.purpleLight,
    route: '/features/pharmacy/screens/MedicineCategoriesScreen',
  },
  {
    id: 'emergency',
    label: 'Emergency\nSOS',
    icon: 'ambulance',
    iconLib: 'mci',
    color: C.emergency,
    bg: C.emergencyLight,
    route: '/features/emergency/screens/EmergencySOSScreen',
  },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────
function getGreeting() {
  const h = new Date().getHours();
  if (h < 12) return 'Good Morning';
  if (h < 17) return 'Good Afternoon';
  return 'Good Evening';
}

function formatDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}

function formatTime(timeStr) {
  if (!timeStr) return '';
  const [h, m] = timeStr.split(':');
  const hour = parseInt(h, 10);
  const ampm = hour >= 12 ? 'PM' : 'AM';
  return `${hour % 12 || 12}:${m} ${ampm}`;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function HeaderSection({ profile, onNotifPress }) {
  return (
    <LinearGradient colors={['#0A5F55', '#12897A']} style={styles.header}>
      <View style={styles.headerTop}>
        <View style={styles.headerLeft}>
          <Text style={styles.greetingText}>{getGreeting()} 👋</Text>
          <Text style={styles.userName} numberOfLines={1}>
            {profile?.name || 'User'}
          </Text>
          <View style={styles.locationRow}>
            <Ionicons name="location-outline" size={13} color="rgba(255,255,255,0.7)" />
            <Text style={styles.locationText}>
              {profile?.city || 'Set location'}
            </Text>
          </View>
        </View>
        <View style={styles.headerRight}>
          <TouchableOpacity style={styles.notifBtn} onPress={onNotifPress}>
            <Ionicons name="notifications-outline" size={22} color="#fff" />
            <View style={styles.notifBadge} />
          </TouchableOpacity>
          <View style={styles.avatarCircle}>
            <Text style={styles.avatarText}>
              {(profile?.name || 'U')[0].toUpperCase()}
            </Text>
          </View>
        </View>
      </View>

      {/* Search bar placeholder */}
      <TouchableOpacity style={styles.searchBar} activeOpacity={0.8}>
        <Ionicons name="search-outline" size={18} color={C.textMuted} />
        <Text style={styles.searchPlaceholder}>Search doctors, tests, medicines…</Text>
      </TouchableOpacity>
    </LinearGradient>
  );
}

function EmergencyBanner({ onPress }) {
  return (
    <TouchableOpacity style={styles.emergencyBanner} onPress={onPress} activeOpacity={0.85}>
      <View style={styles.emergencyLeft}>
        <View style={styles.sosCircle}>
          <Text style={styles.sosText}>SOS</Text>
        </View>
        <View>
          <Text style={styles.emergencyTitle}>Emergency Help</Text>
          <Text style={styles.emergencySubtitle}>Tap to call ambulance instantly</Text>
        </View>
      </View>
      <Ionicons name="chevron-forward" size={20} color={C.emergency} />
    </TouchableOpacity>
  );
}

function StatsRow({ stats }) {
  const items = [
    { label: 'Appointments', value: stats?.total_appointments ?? '-', icon: 'calendar-outline', color: C.primary },
    { label: 'Lab Reports', value: stats?.total_lab_bookings ?? '-', icon: 'flask-outline', color: C.blue },
    { label: 'Orders', value: stats?.total_orders ?? '-', icon: 'bag-outline', color: C.purple },
  ];
  return (
    <View style={styles.statsRow}>
      {items.map((item, i) => (
        <View key={i} style={styles.statCard}>
          <Ionicons name={item.icon} size={20} color={item.color} />
          <Text style={[styles.statValue, { color: item.color }]}>{item.value}</Text>
          <Text style={styles.statLabel}>{item.label}</Text>
        </View>
      ))}
    </View>
  );
}

function QuickServices({ onPress }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>Our Services</Text>
      <View style={styles.servicesGrid}>
        {QUICK_SERVICES.map((s) => (
          <TouchableOpacity
            key={s.id}
            style={[styles.serviceCard, { backgroundColor: s.bg }]}
            onPress={() => onPress(s)}
            activeOpacity={0.75}
          >
            <View style={[styles.serviceIconWrap, { backgroundColor: s.color + '20' }]}>
              {s.iconLib === 'mci' ? (
                <MaterialCommunityIcons name={s.icon} size={26} color={s.color} />
              ) : (
                <Ionicons name={s.icon} size={26} color={s.color} />
              )}
            </View>
            <Text style={[styles.serviceLabel, { color: s.color }]}>{s.label}</Text>
          </TouchableOpacity>
        ))}
      </View>
    </View>
  );
}

function AppointmentCard({ item, onPress }) {
  const statusColor = {
    upcoming: C.primary,
    confirmed: C.blue,
    completed: C.textMuted,
    cancelled: C.emergency,
  };
  const color = statusColor[item.status] || C.textSecondary;

  return (
    <TouchableOpacity style={styles.apptCard} onPress={onPress} activeOpacity={0.8}>
      <View style={[styles.apptColorBar, { backgroundColor: color }]} />
      <View style={styles.apptContent}>
        <View style={styles.apptRow}>
          <View style={styles.apptDocIcon}>
            <Ionicons name="person" size={18} color={C.primary} />
          </View>
          <View style={styles.apptInfo}>
            <Text style={styles.apptDoctorName} numberOfLines={1}>
              Dr. {item.doctor_name || 'Unknown'}
            </Text>
            <Text style={styles.apptSpecialty} numberOfLines={1}>
              {item.specialization || item.department || 'General'}
            </Text>
          </View>
          <View style={[styles.apptStatusBadge, { backgroundColor: color + '18' }]}>
            <Text style={[styles.apptStatusText, { color }]}>
              {item.status?.charAt(0).toUpperCase() + item.status?.slice(1)}
            </Text>
          </View>
        </View>
        <View style={styles.apptFooter}>
          <Ionicons name="calendar-outline" size={13} color={C.textMuted} />
          <Text style={styles.apptDateText}>{formatDate(item.appointment_date)}</Text>
          <Ionicons name="time-outline" size={13} color={C.textMuted} style={{ marginLeft: 8 }} />
          <Text style={styles.apptDateText}>{formatTime(item.appointment_time)}</Text>
        </View>
      </View>
    </TouchableOpacity>
  );
}

function UpcomingAppointments({ appointments, loading, onViewAll, router }) {
  return (
    <View style={styles.section}>
      <View style={styles.sectionHeader}>
        <Text style={styles.sectionTitle}>Upcoming Appointments</Text>
        <TouchableOpacity onPress={onViewAll}>
          <Text style={styles.viewAllText}>View All</Text>
        </TouchableOpacity>
      </View>

      {loading ? (
        <ActivityIndicator color={C.primary} style={{ marginTop: 16 }} />
      ) : appointments.length === 0 ? (
        <View style={styles.emptyCard}>
          <Ionicons name="calendar-outline" size={36} color={C.textMuted} />
          <Text style={styles.emptyText}>No upcoming appointments</Text>
          <TouchableOpacity
            style={styles.bookNowBtn}
            onPress={() => router.push('/features/doctor/screens/DoctorCategoriesScreen')}
          >
            <Text style={styles.bookNowText}>Book a Doctor</Text>
          </TouchableOpacity>
        </View>
      ) : (
        appointments.map((appt) => (
          <AppointmentCard
            key={appt.id}
            item={appt}
            onPress={() =>
              router.push({
                pathname: '/features/doctor/screens/DoctorProfileScreen',
                params: { id: appt.doctor_id },
              })
            }
          />
        ))
      )}
    </View>
  );
}

function HealthTipCard({ tip }) {
  return (
    <LinearGradient
      colors={['#0A5F55', '#1AAD99']}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={styles.tipCard}
    >
      <View style={styles.tipLeft}>
        <Text style={styles.tipEyebrow}>💡 Health Tip</Text>
        <Text style={styles.tipText}>{tip}</Text>
      </View>
      <Ionicons name="heart" size={40} color="rgba(255,255,255,0.15)" />
    </LinearGradient>
  );
}

// ─── Main Screen ──────────────────────────────────────────────────────────────
export default function HomeScreen() {
  const router = useRouter();
  const [profile, setProfile] = useState(null);
  const [dashboardData, setDashboardData] = useState(null);
  const [appointments, setAppointments] = useState([]);
  const [loadingAppts, setLoadingAppts] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);

  const HEALTH_TIPS = [
    'Drink at least 8 glasses of water daily to stay hydrated.',
    'Regular checkups help catch health issues early.',
    'A 30-minute walk daily can significantly improve your health.',
  ];
  const dailyTip = HEALTH_TIPS[new Date().getDate() % HEALTH_TIPS.length];

  const fetchData = useCallback(async () => {
    try {
      const [profileRes, dashRes] = await Promise.allSettled([
        getUserProfile(),
        getDashboardData(),
      ]);
      if (profileRes.status === 'fulfilled') setProfile(profileRes.value);
      if (dashRes.status === 'fulfilled') setDashboardData(dashRes.value);
    } catch (err) {
      // Silent fail for dashboard — not critical
    } finally {
      setInitialLoading(false);
    }
  }, []);

  const fetchAppointments = useCallback(async () => {
    setLoadingAppts(true);
    try {
      const data = await getUpcomingAppointments();
      setAppointments(Array.isArray(data) ? data : data?.results || []);
    } catch (err) {
      setAppointments([]);
    } finally {
      setLoadingAppts(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    fetchAppointments();
  }, []);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([fetchData(), fetchAppointments()]);
    setRefreshing(false);
  }, [fetchData, fetchAppointments]);

  const handleServicePress = (service) => {
    if (service.id === 'emergency') {
      Alert.alert(
        '🚨 Emergency SOS',
        'This will call an ambulance to your current location. Confirm?',
        [
          { text: 'Cancel', style: 'cancel' },
          { text: 'CALL NOW', style: 'destructive', onPress: () => router.push(service.route) },
        ]
      );
    } else {
      router.push(service.route);
    }
  };

  if (initialLoading) {
    return (
      <View style={styles.loadingScreen}>
        <ActivityIndicator size="large" color={C.primary} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={C.primary} />
      <ScrollView
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={C.primary}
            colors={[C.primary]}
          />
        }
      >
        {/* Header */}
        <HeaderSection
          profile={profile}
          onNotifPress={() => router.push('/notifications')}
        />

        <View style={styles.body}>
          {/* Emergency Banner */}
          <EmergencyBanner
            onPress={() => handleServicePress(QUICK_SERVICES[3])}
          />

          {/* Stats */}
          {dashboardData && <StatsRow stats={dashboardData} />}

          {/* Quick Services */}
          <QuickServices onPress={handleServicePress} />

          {/* Upcoming Appointments */}
          <UpcomingAppointments
            appointments={appointments}
            loading={loadingAppts}
            onViewAll={() => router.push('/features/doctor/screens/MyAppointmentsScreen')}
            router={router}
          />

          {/* Health Tip */}
          <View style={styles.section}>
            <HealthTipCard tip={dailyTip} />
          </View>

          <View style={{ height: 24 }} />
        </View>
      </ScrollView>
    </View>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────
const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: C.bg },
  loadingScreen: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: C.bg },
  scrollContent: { flexGrow: 1 },

  // Header
  header: {
    paddingTop: Platform.OS === 'ios' ? 56 : StatusBar.currentHeight + 12,
    paddingHorizontal: 20,
    paddingBottom: 24,
    borderBottomLeftRadius: 28,
    borderBottomRightRadius: 28,
  },
  headerTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 },
  headerLeft: { flex: 1 },
  headerRight: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  greetingText: { fontSize: 13, color: 'rgba(255,255,255,0.75)', fontWeight: '500', marginBottom: 2 },
  userName: { fontSize: 22, fontWeight: '800', color: '#fff', letterSpacing: -0.3 },
  locationRow: { flexDirection: 'row', alignItems: 'center', marginTop: 4, gap: 3 },
  locationText: { fontSize: 12, color: 'rgba(255,255,255,0.7)', fontWeight: '500' },
  notifBtn: { padding: 8, borderRadius: 20, backgroundColor: 'rgba(255,255,255,0.15)', position: 'relative' },
  notifBadge: {
    position: 'absolute', top: 7, right: 7,
    width: 8, height: 8, borderRadius: 4,
    backgroundColor: C.accent, borderWidth: 1.5, borderColor: C.primary,
  },
  avatarCircle: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.25)',
    justifyContent: 'center', alignItems: 'center',
    borderWidth: 2, borderColor: 'rgba(255,255,255,0.5)',
  },
  avatarText: { fontSize: 16, fontWeight: '700', color: '#fff' },
  searchBar: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    backgroundColor: '#fff', borderRadius: 14,
    paddingHorizontal: 14, paddingVertical: 12,
    shadowColor: C.shadow, shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.08, shadowRadius: 6, elevation: 3,
  },
  searchPlaceholder: { fontSize: 14, color: C.textMuted, flex: 1 },

  // Body
  body: { paddingHorizontal: 16, paddingTop: 16 },

  // Emergency Banner
  emergencyBanner: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    backgroundColor: C.emergencyLight,
    borderRadius: 16, padding: 14, marginBottom: 16,
    borderWidth: 1.5, borderColor: '#FADDD9',
  },
  emergencyLeft: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  sosCircle: {
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: C.emergency,
    justifyContent: 'center', alignItems: 'center',
  },
  sosText: { fontSize: 12, fontWeight: '900', color: '#fff', letterSpacing: 1 },
  emergencyTitle: { fontSize: 15, fontWeight: '700', color: C.emergency },
  emergencySubtitle: { fontSize: 12, color: C.textSecondary, marginTop: 1 },

  // Stats
  statsRow: {
    flexDirection: 'row', gap: 10, marginBottom: 20,
  },
  statCard: {
    flex: 1, backgroundColor: C.card, borderRadius: 14,
    padding: 14, alignItems: 'center', gap: 4,
    shadowColor: C.shadow, shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06, shadowRadius: 8, elevation: 2,
  },
  statValue: { fontSize: 22, fontWeight: '800', letterSpacing: -0.5 },
  statLabel: { fontSize: 11, color: C.textMuted, fontWeight: '500', textAlign: 'center' },

  // Section
  section: { marginBottom: 20 },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  sectionTitle: { fontSize: 17, fontWeight: '800', color: C.text, letterSpacing: -0.3 },
  viewAllText: { fontSize: 13, fontWeight: '600', color: C.primary },

  // Services Grid
  servicesGrid: {
    flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginTop: 12,
  },
  serviceCard: {
    width: '47%', borderRadius: 18, padding: 16,
    alignItems: 'flex-start', gap: 10,
    shadowColor: C.shadow, shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06, shadowRadius: 8, elevation: 2,
  },
  serviceIconWrap: {
    width: 48, height: 48, borderRadius: 14,
    justifyContent: 'center', alignItems: 'center',
  },
  serviceLabel: { fontSize: 13, fontWeight: '700', lineHeight: 18 },

  // Appointment Card
  apptCard: {
    backgroundColor: C.card, borderRadius: 16, marginBottom: 10,
    flexDirection: 'row', overflow: 'hidden',
    shadowColor: C.shadow, shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06, shadowRadius: 8, elevation: 2,
  },
  apptColorBar: { width: 4 },
  apptContent: { flex: 1, padding: 14 },
  apptRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 10 },
  apptDocIcon: {
    width: 38, height: 38, borderRadius: 10,
    backgroundColor: C.primaryPale, justifyContent: 'center', alignItems: 'center',
  },
  apptInfo: { flex: 1 },
  apptDoctorName: { fontSize: 15, fontWeight: '700', color: C.text },
  apptSpecialty: { fontSize: 12, color: C.textSecondary, marginTop: 1 },
  apptStatusBadge: { borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4 },
  apptStatusText: { fontSize: 11, fontWeight: '700' },
  apptFooter: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  apptDateText: { fontSize: 12, color: C.textMuted, fontWeight: '500' },

  // Empty state
  emptyCard: {
    backgroundColor: C.card, borderRadius: 16, padding: 28,
    alignItems: 'center', gap: 8,
    borderWidth: 1.5, borderColor: C.border, borderStyle: 'dashed',
  },
  emptyText: { fontSize: 14, color: C.textMuted, fontWeight: '500' },
  bookNowBtn: {
    marginTop: 8, backgroundColor: C.primary,
    paddingHorizontal: 20, paddingVertical: 10, borderRadius: 10,
  },
  bookNowText: { fontSize: 13, fontWeight: '700', color: '#fff' },

  // Health Tip
  tipCard: {
    borderRadius: 18, padding: 20,
    flexDirection: 'row', alignItems: 'center',
    justifyContent: 'space-between',
  },
  tipLeft: { flex: 1, paddingRight: 12 },
  tipEyebrow: { fontSize: 12, fontWeight: '700', color: 'rgba(255,255,255,0.75)', marginBottom: 6 },
  tipText: { fontSize: 14, color: '#fff', fontWeight: '600', lineHeight: 20 },
});