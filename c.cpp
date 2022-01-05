#include <stdio.h>

int main(){
	int a[100000];
	scanf("%s",a);
	for(int i=0; a[i]!='\0';i++){
		printf("%d",a[i]);
	}
}
