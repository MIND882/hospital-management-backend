import apiClient from "@/src/services/apiClient";

export const searchLabTests = (data) =>
  apiClient.post("/lab-tests/search", data);