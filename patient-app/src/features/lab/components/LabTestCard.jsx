import { View, Text } from "react-native";

const LabTestCard = ({ test }) => {
  return (
    <View style={{ padding: 12, borderWidth: 1, marginBottom: 10 }}>
      <Text>{test.test_name}</Text>
      <Text>₹{test.price}</Text>
    </View>
  );
};

export default LabTestCard;