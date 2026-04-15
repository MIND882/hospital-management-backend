import { View, Text } from 'react-native';

export function Collapsible({ title, children }: any) {
  return (
    <View style={{ marginVertical: 10 }}>
      <Text style={{ fontWeight: 'bold' }}>{title}</Text>
      {children}
    </View>
  );
}