import { Tabs } from 'expo-router';
import { View, Text, StyleSheet, Platform } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

const COLORS = {
  primary: '#0A5F55',
  primaryLight: '#12897A',
  accent: '#FF6B35',
  bg: '#F0F4F8',
  tabBg: '#FFFFFF',
  inactive: '#A0ADB8',
  active: '#0A5F55',
};

function TabIcon({
  name,
  focused,
  label,
}: {
  name: keyof typeof Ionicons.glyphMap;
  focused: boolean;
  label: string;
}) {
  return (
    <View style={[styles.tabIconContainer, focused && styles.tabIconActive]}>
      <Ionicons
        name={focused ? name : (`${name}-outline` as keyof typeof Ionicons.glyphMap)}
        size={22}
        color={focused ? COLORS.active : COLORS.inactive}
      />
      <Text style={[styles.tabLabel, focused && styles.tabLabelActive]}>{label}</Text>
      {focused && <View style={styles.activeDot} />}
    </View>
  );
}

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarStyle: styles.tabBar,
        tabBarShowLabel: false,
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          tabBarIcon: ({ focused }) => (
            <TabIcon name="home" focused={focused} label="Home" />
          ),
        }}
      />
      <Tabs.Screen
        name="appointments"
        options={{
          tabBarIcon: ({ focused }) => (
            <TabIcon name="calendar" focused={focused} label="Doctors" />
          ),
        }}
      />
      <Tabs.Screen
        name="lab"
        options={{
          tabBarIcon: ({ focused }) => (
            <TabIcon name="flask" focused={focused} label="Lab" />
          ),
        }}
      />
      <Tabs.Screen
        name="pharmacy"
        options={{
          tabBarIcon: ({ focused }) => (
            <TabIcon name="medkit" focused={focused} label="Pharmacy" />
          ),
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          tabBarIcon: ({ focused }) => (
            <TabIcon name="person" focused={focused} label="Profile" />
          ),
        }}
      />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  tabBar: {
    backgroundColor: COLORS.tabBg,
    borderTopWidth: 0,
    height: Platform.OS === 'ios' ? 85 : 68,
    paddingBottom: Platform.OS === 'ios' ? 20 : 8,
    paddingTop: 8,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: -4 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    elevation: 16,
  },
  tabIconContainer: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 12,
    minWidth: 56,
    position: 'relative',
  },
  tabIconActive: {
    backgroundColor: '#E8F5F3',
  },
  tabLabel: {
    fontSize: 10,
    fontWeight: '500',
    color: COLORS.inactive,
    marginTop: 2,
  },
  tabLabelActive: {
    color: COLORS.active,
    fontWeight: '700',
  },
  activeDot: {
    position: 'absolute',
    bottom: -2,
    width: 4,
    height: 4,
    borderRadius: 2,
    backgroundColor: COLORS.active,
  },
});