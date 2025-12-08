from firebase import firebase
url = 'https://ntuiot-f7743-default-rtdb.firebaseio.com'
fdb = firebase.FirebaseApplication(url, None)
#fdb.post('/product',{'id':0, 'name':"noodle","table_id":1,"number":10})
#fdb.post('/product',{'id':1, 'name':"water","table_id":2,"number":10})
result = fdb.get('/','product')
print(result)  
# fdb.patch('/product/1', {
#     'number': 5         # 只改 number，其它欄位保持不變
# })

fdb.patch('/product/-Oe6MqbS2lFp5KD07uqE', 
          {'id': 1, 'name': 'water', 'number': 50, 'table_id': 2})