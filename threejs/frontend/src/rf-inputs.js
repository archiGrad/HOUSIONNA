// Sionna RT 2.2.0 orientation is [alpha about Z, beta about Y, gamma about X].
export function orientationWithYaw(orientation, degrees) {
  const yaw=Number(degrees)*Math.PI/180;
  if(!Number.isFinite(yaw))throw new Error('TX yaw must be finite.');
  return [yaw,Number(orientation?.[1]||0),Number(orientation?.[2]||0)];
}

export function finiteRange(values){
  let min=Infinity,max=-Infinity,count=0;
  for(const raw of values){if(raw==null)continue;const value=Number(raw);if(!Number.isFinite(value))continue;min=Math.min(min,value);max=Math.max(max,value);count++;}
  return {min:count?min:0,max:count?max:0,count};
}
