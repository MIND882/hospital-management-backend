import { Linking, Text } from 'react-native';

export function ExternalLink({ href, children }: any) {
  return (
    <Text style={{ color: 'blue' }} onPress={() => Linking.openURL(href)}>
      {children}
    </Text>
  );
}