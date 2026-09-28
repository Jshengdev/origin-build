/** Mock saved locations the dog can be sent to. The dock is where it starts. */
export interface Place { id: string; name: string; position: [number, number] }

export const HOME_ID = "home";
export const SAVED_PLACES: Place[] = [
  { id: HOME_ID, name: "Home dock", position: [8.2, 1.4] },
  { id: "front-door", name: "Front door", position: [6.2, 1.8] },
  { id: "kitchen", name: "Kitchen", position: [3.5, 7.5] },
  { id: "garage", name: "Garage door", position: [14.2, 1.2] },
];
